import time

from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from core.logger import get_logger

from db.mongo_app import MongoApp

from services.preload_service import PreloadService
from config.settings import Settings
from services.candle_builder import CandleBuilder
from services.market_status_service import MarketStatusService
from services.crossover_engine import CrossoverEngine

from services.upstox_stream import UpstoxStreamService

logger = get_logger(__name__)


class MarketScheduler:

    # ----------------------------------------------------
    # 1. Modify Constructor to Accept Notifier Instance
    # ----------------------------------------------------
    def __init__(self, notifier=None):

        self.notifier = notifier  # Store telegram service instance
        self.stream_service = None

        self.ist = ZoneInfo("Asia/Kolkata")

        self.preloaded_today = False
        self.market_started = False
        self.market_closed_today = False

        self.market_closed_logged = False
        self.market_holiday_logged = False

        self.current_trading_date = None
        self.access_token = None

        # NEW
        self.market_open_today = False

    def get_today(self):

        return datetime.now(self.ist).date().isoformat()

    def get_current_time(self):

        return datetime.now(self.ist).time()

    def is_day_refresh_time(self):

        return self.get_current_time() >= dt_time(7, 0)

    def is_preload_time(self):

        return self.get_current_time() >= Settings.PRELOAD_TIME

    def is_market_open_time(self):

        return self.get_current_time() >= Settings.MARKET_START_TIME

    def is_market_closed_time(self):

        return self.get_current_time() >= Settings.MARKET_END_TIME

    def reset_for_new_day(self):

        try:

            today = self.get_today()

            if self.current_trading_date == today:
                return

            # Do not roll to the new day before 7 AM

            if not self.is_day_refresh_time():

                return

            self.market_closed_logged = False
            self.market_holiday_logged = False

            logger.info(f"New trading day detected: {today}")

            self.current_trading_date = today

            self.preloaded_today = False

            self.market_started = False

            self.market_closed_today = False

            self.market_open_today = MarketStatusService.is_market_open_today()

            logger.info(f"Market Open Today = {self.market_open_today}")

        except Exception as ex:

            logger.exception(f"Reset day failed: {ex}")
            if self.notifier:
                self.notifier.send_critical_alert("Day Reset Initialization", str(ex))

    def perform_preload(self):
        """
        Daily preload.
        """

        try:
            logger.info("=" * 70)
            logger.info("STARTING DAILY PRELOAD")
            logger.info("=" * 70)

            # Start timer to measure preload duration
            start_time = time.time()

            PreloadService.RUNTIME_STATE.clear()

            self.access_token = PreloadService.load_access_token()

            # Simple check to guarantee an access token was retrieved
            if not self.access_token:
                raise ValueError("Access token is missing or empty in MongoDB.")

            runtime_state = PreloadService.initialize_runtime_state()

            total = len(runtime_state)

            logger.info(f"Daily preload complete | Instruments={total}")

            PreloadService.print_startup_summary()

            self.preloaded_today = True

            # ----------------------------------------------------
            # Fire Telegram Preload Summary Notification
            # ----------------------------------------------------
            if self.notifier:
                duration = time.time() - start_time
                self.notifier.send_preload_summary(
                    total_strikes=total, duration_secs=duration
                )

        except Exception as ex:
            logger.exception(f"Daily preload failed: {ex}")

            if self.notifier:
                # Check if the exception points to an expired or invalid token session
                error_str = str(ex).lower()
                if (
                    "unauthorized" in error_str
                    or "expired" in error_str
                    or "token" in error_str
                ):
                    self.notifier.send_upstox_token_expired(
                        date_str=self.get_today(), error_details=str(ex)
                    )
                else:
                    # Fallback to general critical error tracking if it's a structural DB/code crash
                    self.notifier.send_critical_alert(
                        "Daily Strike Preload Phase", str(ex)
                    )

    def start_market(self):
        """
        Start live streaming.
        """

        try:

            if self.market_started:
                return

            logger.info("=" * 70)
            logger.info("MARKET OPEN - STARTING FEED")
            logger.info("=" * 70)

            self.stream_service = UpstoxStreamService(self.access_token)

            self.stream_service.start()

            self.market_started = True

            logger.info("Market feed started.")

        except Exception as ex:

            logger.exception(f"Market start failed: {ex}")
            if self.notifier:
                self.notifier.send_critical_alert("Market Live Stream Start", str(ex))

    def flush_pending_candles(self):
        """
        Flush all active candles.
        """
        success_count = 0
        failed_count = 0

        try:

            active_candles = dict(CandleBuilder.ACTIVE_CANDLES)

            logger.info(f"Flushing " f"{len(active_candles)} " f"active candles")

            for instrument_key in list(active_candles.keys()):

                try:

                    candle = CandleBuilder.force_close_candle(instrument_key)

                    if candle:

                        CrossoverEngine.process_completed_candle(instrument_key, candle)
                        success_count += 1

                except Exception as ex:

                    logger.exception(f"Flush failed " f"{instrument_key}: {ex}")
                    failed_count += 1

        except Exception as ex:

            logger.exception(f"Flush active candles failed: {ex}")

        return success_count, failed_count

    def stop_market(self):
        """
        Market close cleanup.
        """

        try:

            if self.market_closed_today:
                return

            logger.info("=" * 70)
            logger.info("MARKET CLOSED")
            logger.info("=" * 70)

            # Track processing success/failure variables during EOD flush
            success_count, failed_count = self.flush_pending_candles()

            if self.stream_service:

                try:

                    self.stream_service.stop()

                except Exception as ex:

                    logger.exception(f"Socket stop failed: {ex}")
                    if self.notifier:
                        self.notifier.send_critical_alert(
                            "Socket Closure Action", str(ex)
                        )

            runtime_count = len(PreloadService.RUNTIME_STATE)

            active_count = len(CandleBuilder.ACTIVE_CANDLES)

            logger.info(f"Runtime Instruments=" f"{runtime_count}")

            logger.info(f"Active Candles=" f"{active_count}")

            PreloadService.RUNTIME_STATE.clear()

            CandleBuilder.clear()

            self.market_closed_today = True

            self.market_started = False

            logger.info("Market cleanup completed.")

            # ----------------------------------------------------
            # 3. Fire Session Conclusion Notification
            # ----------------------------------------------------
            if self.notifier:
                self.notifier.send_market_stopped_summary(
                    date_str=self.get_today(),
                    success_count=success_count,
                    failed_count=failed_count,
                )

        except Exception as ex:

            logger.exception(f"Market stop failed: {ex}")
            if self.notifier:
                self.notifier.send_critical_alert("Market Cleanup Execution", str(ex))

    def scheduler_cycle(self):
        """
        One scheduler cycle.
        """

        try:

            self.reset_for_new_day()

            today = self.get_today()

            if not self.market_open_today:

                if not self.market_holiday_logged:

                    logger.info(f"Market holiday/weekend ({today})")

                    logger.info("Waiting for next trading day...")

                    self.market_holiday_logged = True

                    # ----------------------------------------------------
                    # 4. Fire Holiday/Weekend Telegram Notice
                    # ----------------------------------------------------
                    if self.notifier:
                        self.notifier.send_market_skipped(
                            date_str=today, reason="NSE Trading Holiday or Weekend"
                        )

                return

            if self.is_market_closed_time():

                if not self.market_closed_logged:

                    logger.info("=" * 70)

                    logger.info(f"TRADING SESSION COMPLETED ({today})")

                    logger.info("Market already closed.")

                    logger.info("Waiting for next trading day...")

                    logger.info("=" * 70)

                    self.market_closed_logged = True

                return

            # -------------------------
            # Daily preload
            # -------------------------

            if (
                not self.preloaded_today
                and self.market_open_today
                and self.is_preload_time()
            ):

                logger.info(f"Running preload " f"for {today}")

                self.perform_preload()

            # -------------------------
            # Start market feed
            # -------------------------

            if (
                self.preloaded_today
                and self.market_open_today
                and not self.market_started
                and self.is_market_open_time()
            ):

                self.start_market()

            # -------------------------
            # Market close
            # -------------------------

            if self.market_started and self.is_market_closed_time():

                self.stop_market()

        except Exception as ex:

            logger.exception(f"Scheduler cycle failed: {ex}")
            if self.notifier:
                self.notifier.send_critical_alert("Internal Scheduler Cycle", str(ex))

    def start(self):
        """
        Main scheduler loop.
        """

        logger.info("=" * 80)
        logger.info("MARKET SCHEDULER STARTED")
        logger.info("=" * 80)

        MongoApp.connect()

        while True:

            try:

                self.scheduler_cycle()

            except Exception as ex:

                logger.exception(f"Scheduler error: {ex}")
                if self.notifier:
                    self.notifier.send_critical_alert(
                        "Main Scheduler Thread Core Failure", str(ex)
                    )

            time.sleep(15)
