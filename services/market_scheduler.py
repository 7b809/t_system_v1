# services/market_scheduler.py

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as datetime_time, timedelta, timezone

import upstox_client
from upstox_client.rest import ApiException

from core.config import settings
from core.logger import get_logger
from core.time_utils import (
    get_ist_date_str,
    get_ist_formatted,
    get_ist_now,
)
from services.ema_calculator import ema_calculator
from services.live_ema_service import live_ema_service
from services.market_analysis_cache import market_analysis_cache
from services.telegram_service import telegram_service
from services.upstox_service import upstox_service

logger = get_logger("market_scheduler")

# Indian Standard Time (+05:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))


class MarketScheduler:
    """
    Background scheduler for handling live daily EMA cross calculations.

    Workflow:
      - Valid Trading Days (09:10 AM - 09:15 AM): Reloads cache & resets MongoDB structure.
      - Valid Trading Days (09:15 AM - 03:30 PM): Processes 1-minute intraday candles in parallel using threads.
      - Post-Market Recovery Mode (After 03:30 PM): Checks if today's calculations were missed and backfills them in parallel.
      - Off-hours / Weekends / Market Holidays: Calculates exact sleep duration until the next valid trading day.
    """

    def __init__(self, max_workers: int = 10):
        self.is_running = False
        self.has_reset_today = False
        self.has_notified_market_close = False
        self.has_run_recovery_today = False
        self.max_workers = max_workers

        # Initialize Upstox Holiday & Timing API Instance
        config = upstox_client.Configuration()
        self.holidays_api = upstox_client.MarketHolidaysAndTimingsApi(
            upstox_client.ApiClient(config)
        )

    def is_trading_day(self, date_str: str) -> bool:
        """
        Queries Upstox MarketHolidaysAndTimingsApi to check if the date is an active trading day.
        Returns True if exchange timings (NSE/NFO/BSE) exist; False if data is empty (Holiday/Closed).
        """
        try:
            api_response = self.holidays_api.get_exchange_timings(date_str)
            response_dict = (
                api_response.to_dict()
                if hasattr(api_response, "to_dict")
                else api_response
            )

            data = response_dict.get("data", [])
            status = response_dict.get("status")

            if status == "success" and data:
                # Check if key equities/derivatives exchanges are active
                for item in data:
                    exchange = (
                        item.get("exchange")
                        if isinstance(item, dict)
                        else getattr(item, "exchange", None)
                    )
                    if exchange in ["NSE", "NFO", "BSE"]:
                        return True
                return len(data) > 0

            return False

        except ApiException as e:
            logger.error(
                f"Upstox API Exception when checking market timings for {date_str}: {e}"
            )
            # Fallback assumption if API fails: allow default processing
            return True
        except Exception as e:
            logger.error(
                f"Unexpected error checking market timings for {date_str}: {e}"
            )
            return True

    def _get_seconds_until_next_pre_market(self, now: datetime) -> float:
        """
        Calculates the exact number of seconds to sleep until 09:10:00 AM IST
        of the next valid trading day (Skipping weekends and Upstox market holidays).
        """
        target_time = datetime_time(9, 10, 0)
        today_pre_market = datetime.combine(now.date(), target_time, tzinfo=IST_TZ)

        # Determine initial candidate day
        if now < today_pre_market:
            target_date = now.date()
        else:
            target_date = now.date() + timedelta(days=1)

        # Skip Weekends (Sat=5, Sun=6) and Upstox Market Holidays (data: [])
        while True:
            # Step 1: Skip weekends
            if target_date.weekday() in (5, 6):
                target_date += timedelta(days=1)
                continue

            # Step 2: Skip holidays verified via Upstox API
            target_date_str = target_date.strftime("%Y-%m-%d")
            if not self.is_trading_day(target_date_str):
                logger.info(
                    f"Date {target_date_str} is flagged as a Market Holiday by Upstox. Skipping to next day..."
                )
                target_date += timedelta(days=1)
                continue

            # Valid trading day found
            break

        next_pre_market = datetime.combine(target_date, target_time, tzinfo=IST_TZ)
        seconds_remaining = (next_pre_market - now).total_seconds()

        return max(seconds_remaining, 1.0)

    def _process_single_instrument(self, doc: dict, date_str: str) -> bool:
        """
        Worker task for processing a single cached instrument in a worker thread.
        Returns True if processing/saving was successful, False otherwise.
        """
        # Extract instrument_key from cached document or daily fallback
        instrument_key = doc.get("instrument_key")

        if not instrument_key and "daily" in doc:
            daily_dict = doc.get("daily", {})
            if daily_dict:
                latest_day = max(daily_dict.keys())
                instrument_key = daily_dict[latest_day].get("instrument_key")

        if not instrument_key:
            return False

        # Step A: Fetch 1-minute intraday candles
        candles = upstox_service.fetch_intraday_candles(
            instrument_key=instrument_key,
            unit="minutes",
            interval="1",
        )

        if not candles:
            return False

        # Step B: Calculate EMA 9 / EMA 21 crossovers
        crosses = ema_calculator.calculate_ema_crosses(candles)

        # Step C: Update live EMA results in MongoDB
        live_ema_service.save_instrument_crosses(
            date_str=date_str,
            instrument_key=instrument_key,
            crosses=crosses,
        )
        return True

    def _recover_single_instrument(self, doc: dict, date_str: str) -> bool:
        """
        Worker task for recovering missing instrument data in recovery mode inside a worker thread.
        Returns True if data was recovered, False otherwise.
        """
        instrument_key = doc.get("instrument_key")

        if not instrument_key and "daily" in doc:
            daily_dict = doc.get("daily", {})
            if daily_dict:
                latest_day = max(daily_dict.keys())
                instrument_key = daily_dict[latest_day].get("instrument_key")

        if not instrument_key:
            return False

        # Check if today's calculations already exist in MongoDB
        existing_data = live_ema_service.get_instrument_crosses(
            date_str=date_str, instrument_key=instrument_key
        )

        # If data is missing or empty, execute recovery backfill
        if not existing_data or not existing_data.get("crosses"):
            logger.info(
                f"Recovery required for instrument: {instrument_key}. Fetching candles..."
            )

            candles = upstox_service.fetch_intraday_candles(
                instrument_key=instrument_key,
                unit="minutes",
                interval="1",
            )

            if candles:
                crosses = ema_calculator.calculate_ema_crosses(candles)
                live_ema_service.save_instrument_crosses(
                    date_str=date_str,
                    instrument_key=instrument_key,
                    crosses=crosses,
                )
                logger.info(
                    f"Successfully recovered {len(crosses)} EMA cross signals for {instrument_key}."
                )
                return True

        return False

    async def _process_all_live_parallel(
        self, all_cached: dict, date_str: str
    ) -> float:
        """
        Executes parallel multi-threaded fetching for all instruments during live market hours.
        Calculates exact processing duration and returns remaining idle seconds needed
        to align perfectly with the next minute boundary.
        """
        total_items = len(all_cached)
        start_dt = get_ist_now()
        start_perf = time.perf_counter()

        logger.info(
            f"[{start_dt.strftime('%H:%M:%S IST')}] 🚀 Started fetching & calculating live EMA crosses for "
            f"{total_items} instruments using pool of {self.max_workers} threads..."
        )

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            tasks = [
                loop.run_in_executor(
                    executor,
                    self._process_single_instrument,
                    doc,
                    date_str,
                )
                for doc in all_cached.values()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed_time = time.perf_counter() - start_perf
        successful_count = sum(1 for r in results if r is True)
        end_dt = get_ist_now()

        # Target next minute start (00 seconds)
        next_minute_dt = (end_dt + timedelta(minutes=1)).replace(
            second=0, microsecond=0
        )
        sleep_seconds = max((next_minute_dt - end_dt).total_seconds(), 1.0)

        logger.info(
            f"[{end_dt.strftime('%H:%M:%S IST')}] ✅ Completed live execution cycle. "
            f"Processed: {successful_count}/{total_items} instruments | "
            f"Started at: {start_dt.strftime('%H:%M:%S')} | "
            f"Processing Time: {elapsed_time:.2f}s | "
            f"Idle Sleep: {sleep_seconds:.2f}s | "
            f"Next Start: {next_minute_dt.strftime('%H:%M:%S')}"
        )

        return sleep_seconds

    async def run_recovery_mode(self, date_str: str) -> None:
        """
        Post-market recovery routine with parallel processing.
        Checks if today's EMA cross data is missing in MongoDB for cached instruments.
        If missing, fetches full day intraday candles, calculates crossovers, and saves them.
        """
        logger.info(
            f"🔄 Entering Recovery Mode for Date: {date_str}... Checking for missing EMA cross data."
        )

        all_cached = market_analysis_cache.get_all()
        if not all_cached:
            logger.warning(
                "Cache empty. Reloading market analysis cache for recovery mode..."
            )
            market_analysis_cache.reload()
            all_cached = market_analysis_cache.get_all()

        total_items = len(all_cached)
        logger.info(
            f"🚀 Parallel Recovery Mode started for {total_items} instruments with {self.max_workers} workers..."
        )

        start_time = time.perf_counter()

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            tasks = [
                loop.run_in_executor(
                    executor,
                    self._recover_single_instrument,
                    doc,
                    date_str,
                )
                for doc in all_cached.values()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed_time = time.perf_counter() - start_time
        recovered_count = sum(1 for r in results if r is True)

        self.has_run_recovery_today = True
        logger.info(
            f"✅ Recovery Mode completed. Processed: {total_items}, "
            f"Recovered: {recovered_count} instruments. "
            f"Time taken: {elapsed_time:.2f} seconds."
        )

        # Telegram notification for completed recovery backfill
        if recovered_count > 0:
            await telegram_service.send_message(
                f"🛠️ <b>Post-Market Recovery Completed</b>\n"
                f"<b>Date:</b> {date_str}\n"
                f"<b>Recovered Instruments:</b> {recovered_count}/{total_items}\n"
                f"<b>Execution Time:</b> {elapsed_time:.2f}s\n"
                f"<b>Time:</b> {get_ist_formatted()}"
            )

    async def start(self) -> None:
        """Starts the background processing loop."""
        self.is_running = True
        logger.info(
            f"Market Scheduler service initialized and started at: {get_ist_formatted()}"
        )

        while self.is_running:
            is_off_hours = False
            sleep_seconds = settings.SCHEDULER_SLEEP_SECONDS

            try:
                now = get_ist_now()
                date_str = get_ist_date_str()
                formatted_time = get_ist_formatted()

                # Verify if today is a valid weekday AND an active trading day via Upstox
                is_weekday = now.weekday() < 5
                is_active_session = is_weekday and self.is_trading_day(date_str)

                # ------------------------------------------------------------------
                # 1. Pre-Market Phase (09:10 AM - 09:15 AM on Valid Trading Days)
                # ------------------------------------------------------------------
                if is_active_session and now.hour == 9 and 10 <= now.minute < 15:
                    if not self.has_reset_today:
                        logger.info(
                            f"[{formatted_time}] Executing pre-market daily reset..."
                        )

                        # Reload market cache from MongoDB
                        market_analysis_cache.reload()
                        all_cached = market_analysis_cache.get_all()

                        # Reset daily structures in live_ema_analysis
                        live_ema_service.reset_today_cache(date_str, all_cached)

                        self.has_reset_today = True
                        self.has_notified_market_close = False
                        self.has_run_recovery_today = False

                        logger.info(
                            f"[{formatted_time}] Pre-market daily reset completed successfully."
                        )

                        # Telegram Alert for Pre-Market Daily Reset
                        await telegram_service.notify_pre_market_reset()

                # ------------------------------------------------------------------
                # 2. Live Market Hours Phase (09:15 AM - 03:30 PM on Valid Trading Days)
                # ------------------------------------------------------------------
                elif is_active_session and (
                    (now.hour == 9 and now.minute >= 15)
                    or (10 <= now.hour < 15)
                    or (now.hour == 15 and now.minute <= 30)
                ):
                    all_cached = market_analysis_cache.get_all()

                    if not all_cached:
                        logger.warning(
                            "Cache is empty. Reloading market analysis cache..."
                        )
                        market_analysis_cache.reload()
                        all_cached = market_analysis_cache.get_all()

                        # Telegram Alert when Cache Reloads during Market Hours
                        await telegram_service.send_message(
                            f"🔄 <b>Cache Reloaded during Market Hours</b>\n"
                            f"<b>Date:</b> {date_str}\n"
                            f"<b>Total Items:</b> {market_analysis_cache.count()}\n"
                            f"<b>Time:</b> {formatted_time}"
                        )

                    # Parallel execution returning dynamically calculated sleep alignment time
                    sleep_seconds = await self._process_all_live_parallel(
                        all_cached, date_str
                    )

                # ------------------------------------------------------------------
                # 3. Outside Market Hours / Recovery / Holidays (Long Sleep Calculation)
                # ------------------------------------------------------------------
                else:
                    is_off_hours = True
                    logger.info(
                        f"[{formatted_time}] Outside active market hours / Holiday / Weekend."
                    )

                    # --------------------------------------------------------------
                    # 3A. Post-Market Recovery Check (Triggered after 03:30 PM IST)
                    # --------------------------------------------------------------
                    if (
                        is_active_session
                        and ((now.hour == 15 and now.minute > 30) or now.hour >= 16)
                        and not self.has_run_recovery_today
                    ):
                        await self.run_recovery_mode(date_str)

                    # Trigger Market Close Telegram Notification once after 03:30 PM on trading days
                    if (
                        is_active_session
                        and ((now.hour == 15 and now.minute > 30) or now.hour >= 16)
                        and not self.has_notified_market_close
                    ):
                        self.has_notified_market_close = True
                        await telegram_service.notify_market_close()

                    # Calculate seconds remaining until next valid trading day 09:10 AM IST
                    sleep_seconds = self._get_seconds_until_next_pre_market(now)
                    hours = int(sleep_seconds // 3600)
                    minutes = int((sleep_seconds % 3600) // 60)

                    target_day_str = (now + timedelta(seconds=sleep_seconds)).strftime(
                        "%A, %Y-%m-%d"
                    )

                    logger.info(
                        f"Scheduler entering long sleep mode for {hours}h {minutes}m ({int(sleep_seconds)}s) "
                        f"until 09:10 AM IST on {target_day_str}."
                    )

                # ------------------------------------------------------------------
                # 4. Post-Market Reset State Trigger
                # ------------------------------------------------------------------
                if now.hour >= 16 and self.has_reset_today:
                    self.has_reset_today = False
                    self.has_run_recovery_today = False
                    logger.info(
                        f"[{formatted_time}] Market closed. Reset scheduler state for next trading day."
                    )

            except Exception as e:
                logger.error(f"Error occurred in MarketScheduler loop: {e}")
                # Telegram Alert for Exception/Error inside the scheduler loop
                await telegram_service.notify_error(
                    context="MarketScheduler Loop", error_msg=str(e)
                )

            # Execution sleep logic
            if not is_off_hours:
                logger.info(
                    f"Sleeping for {sleep_seconds:.2f} seconds... Next execution cycle scheduled shortly."
                )

            await asyncio.sleep(sleep_seconds)

    def stop(self) -> None:
        """Stops the scheduler loop."""
        logger.info(f"Stopping Market Scheduler at: {get_ist_formatted()}")
        self.is_running = False


# Singleton export
market_scheduler = MarketScheduler()
