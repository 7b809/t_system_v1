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
from services.dashboard_state import DashboardState

logger = get_logger(__name__)


class MarketScheduler:

    def __init__(self, notifier=None):

        self.notifier = notifier
        self.stream_service = None

        self.ist = ZoneInfo(Settings.TIMEZONE)

        self.preloaded_today = False
        self.market_started = False
        self.market_closed_today = False

        self.market_closed_logged = False
        self.market_holiday_logged = False

        self.current_trading_date = None
        self.access_token = None

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
                DashboardState.update_scheduler_status("WAITING_FOR_DAY_REFRESH_TIME")
                return

            self.market_closed_logged = False
            self.market_holiday_logged = False

            logger.info(f"New trading day detected: {today}")

            self.current_trading_date = today

            self.preloaded_today = False
            self.market_started = False
            self.market_closed_today = False

            self.access_token = None
            PreloadService.ACCESS_TOKEN = None

            DashboardState.update_market_status(
                market_status="NEW_TRADING_DAY",
                trading_date=today,
                preloaded_today=False,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status(f"NEW_TRADING_DAY_DETECTED_{today}")

            self.market_open_today = MarketStatusService.is_market_open_today()

            logger.info(f"Market Open Today = {self.market_open_today}")

            if self.market_open_today:
                DashboardState.update_market_status(
                    market_status="MARKET_DAY_CONFIRMED",
                    trading_date=today,
                    preloaded_today=False,
                    market_started=False,
                    market_closed_today=False,
                )

                DashboardState.update_scheduler_status("MARKET_OPEN_TODAY_TRUE")

            else:
                DashboardState.set_market_holiday(
                    trading_date=today,
                    reason="NSE_TRADING_HOLIDAY_OR_WEEKEND",
                )

        except Exception as ex:

            logger.exception(f"Reset day failed: {ex}")

            DashboardState.update_scheduler_status("DAY_RESET_FAILED")

            if self.notifier:
                self.notifier.send_critical_alert(
                    "Day Reset Initialization",
                    str(ex),
                )

    def _try_load_access_token(self):
        """
        Try loading Upstox access token.

        Token is required only for live feed subscription.
        Token is not required for:
        - MongoDB operations
        - Intraday candle recovery using HistoryApi
        """

        try:
            token = PreloadService.load_access_token()

            if token:
                self.access_token = token
                PreloadService.ACCESS_TOKEN = token

                DashboardState.update_scheduler_status("UPSTOX_ACCESS_TOKEN_READY")

                logger.info("Upstox access token loaded successfully.")

                return token

            DashboardState.update_scheduler_status("UPSTOX_ACCESS_TOKEN_EMPTY")

            logger.warning("Upstox access token is empty.")

            return None

        except Exception as ex:
            logger.exception(f"Failed loading Upstox access token: {ex}")

            DashboardState.update_scheduler_status("UPSTOX_ACCESS_TOKEN_LOAD_FAILED")

            return None

    def perform_preload(self):
        """
        Daily preload.

        Preload responsibilities:
        - Load strikes from MongoDB
        - Build runtime EMA state
        - Run intraday recovery if application starts during market hours

        Important:
        Intraday candle recovery does not require Upstox access token.
        Therefore preload should not fail only because token is missing.

        Token is still attempted here so it is ready before market open,
        but it is mandatory only in start_market().
        """

        try:

            logger.info("=" * 70)
            logger.info("STARTING DAILY PRELOAD")
            logger.info("=" * 70)

            DashboardState.update_market_status(
                market_status="PRELOADING",
                trading_date=self.get_today(),
                preloaded_today=False,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("DAILY_PRELOAD_STARTED")

            start_time = time.time()

            PreloadService.reset()

            # --------------------------------------------------
            # Optional token preload.
            # Token is NOT required for runtime preload/recovery.
            # It is required later for live websocket feed.
            # --------------------------------------------------
            token = self._try_load_access_token()

            if not token:
                logger.warning(
                    "Upstox token not available during preload. "
                    "Continuing preload because token is required only "
                    "for live feed subscription."
                )

                DashboardState.update_scheduler_status(
                    "PRELOAD_CONTINUING_WITHOUT_UPSTOX_TOKEN"
                )

            runtime_state = PreloadService.initialize_runtime_state()

            total = len(runtime_state)

            if self.notifier and PreloadService.should_run_intraday_recovery():
                self.notifier.send_intraday_recovery_summary(
                    recovered_instruments=total,
                )

            logger.info(f"Daily preload complete | Instruments={total}")

            PreloadService.print_startup_summary()

            self.preloaded_today = True

            duration = time.time() - start_time

            DashboardState.load_runtime_state(runtime_state)

            DashboardState.update_market_status(
                market_status="PRELOAD_COMPLETE",
                trading_date=self.get_today(),
                preloaded_today=True,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status(
                f"DAILY_PRELOAD_COMPLETE_TOTAL_{total}"
            )

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            if self.notifier:

                self.notifier.send_preload_summary(
                    total_strikes=total,
                    duration_secs=duration,
                )

        except Exception as ex:

            logger.exception(f"Daily preload failed: {ex}")

            DashboardState.update_market_status(
                market_status="PRELOAD_FAILED",
                trading_date=self.get_today(),
                preloaded_today=False,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("DAILY_PRELOAD_FAILED")

            if self.notifier:

                self.notifier.send_critical_alert(
                    "Daily Strike Preload Phase",
                    str(ex),
                )

    def start_market(self):
        """
        Start live streaming.

        Upstox access token is mandatory here because live feed subscription
        uses MarketDataStreamerV3.
        """

        try:

            if self.market_started:
                DashboardState.update_scheduler_status("MARKET_ALREADY_STARTED")
                return

            logger.info("=" * 70)
            logger.info("MARKET OPEN - STARTING FEED")
            logger.info("=" * 70)

            DashboardState.update_market_status(
                market_status="OPENING_FEED",
                trading_date=self.get_today(),
                preloaded_today=self.preloaded_today,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("MARKET_OPEN_STARTING_FEED")

            # --------------------------------------------------
            # Token is required only here for live feed.
            # If token was not loaded during preload, try again now.
            # --------------------------------------------------
            if not self.access_token:
                DashboardState.update_scheduler_status(
                    "MARKET_FEED_TOKEN_MISSING_LOADING_NOW"
                )

                self._try_load_access_token()

            if not self.access_token:
                raise ValueError(
                    "Upstox access token is missing or empty. "
                    "Live market feed cannot start without token."
                )

            self.stream_service = UpstoxStreamService(self.access_token)

            self.stream_service.start()

            self.market_started = True

            DashboardState.update_market_status(
                market_status="OPEN",
                trading_date=self.get_today(),
                preloaded_today=self.preloaded_today,
                market_started=True,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("MARKET_FEED_STARTED")

            logger.info("Market feed started.")

        except Exception as ex:

            logger.exception(f"Market start failed: {ex}")

            DashboardState.update_market_status(
                market_status="MARKET_START_FAILED",
                trading_date=self.get_today(),
                preloaded_today=self.preloaded_today,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("MARKET_FEED_START_FAILED")

            if self.notifier:

                error_str = str(ex).lower()

                if (
                    "unauthorized" in error_str
                    or "expired" in error_str
                    or "token" in error_str
                ):
                    self.notifier.send_upstox_token_expired(
                        date_str=self.get_today(),
                        error_details=str(ex),
                    )

                else:
                    self.notifier.send_critical_alert(
                        "Market Live Stream Start",
                        str(ex),
                    )

    def flush_pending_candles(self):
        """
        Flush all active candles.
        """

        success_count = 0
        failed_count = 0

        try:

            active_candles = dict(CandleBuilder.ACTIVE_CANDLES)

            logger.info(f"Flushing {len(active_candles)} active candles")

            DashboardState.update_scheduler_status(
                f"MARKET_CLOSE_FLUSHING_{len(active_candles)}_CANDLES"
            )

            for instrument_key in list(active_candles.keys()):

                try:

                    candle = CandleBuilder.force_close_candle(instrument_key)

                    if candle:

                        CrossoverEngine.process_completed_candle(
                            instrument_key,
                            candle,
                        )

                        success_count += 1

                except Exception as ex:

                    logger.exception(f"Flush failed {instrument_key}: {ex}")

                    failed_count += 1

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            DashboardState.update_scheduler_status(
                f"MARKET_CLOSE_FLUSH_COMPLETE_SUCCESS_{success_count}_FAILED_{failed_count}"
            )

        except Exception as ex:

            logger.exception(f"Flush active candles failed: {ex}")

            DashboardState.update_scheduler_status("MARKET_CLOSE_FLUSH_FAILED")

        return success_count, failed_count

    def stop_market(self):
        """
        Market close cleanup.
        """

        try:

            if self.market_closed_today:
                DashboardState.update_scheduler_status("MARKET_ALREADY_CLOSED_TODAY")
                return

            logger.info("=" * 70)
            logger.info("MARKET CLOSED")
            logger.info("=" * 70)

            DashboardState.update_market_status(
                market_status="CLOSING",
                trading_date=self.get_today(),
                preloaded_today=self.preloaded_today,
                market_started=self.market_started,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status("MARKET_CLOSE_CLEANUP_STARTED")

            success_count, failed_count = self.flush_pending_candles()

            if self.stream_service:

                try:

                    self.stream_service.stop()

                    DashboardState.set_websocket_disconnected()

                except Exception as ex:

                    logger.exception(f"Socket stop failed: {ex}")

                    DashboardState.update_scheduler_status(
                        "MARKET_CLOSE_SOCKET_STOP_FAILED"
                    )

                    if self.notifier:
                        self.notifier.send_critical_alert(
                            "Socket Closure Action",
                            str(ex),
                        )

            runtime_count = len(PreloadService.RUNTIME_STATE)
            active_count = len(CandleBuilder.ACTIVE_CANDLES)

            logger.info(f"Runtime Instruments={runtime_count}")
            logger.info(f"Active Candles={active_count}")

            PreloadService.reset()
            CandleBuilder.clear()

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            self.market_closed_today = True
            self.market_started = False
            self.stream_service = None

            DashboardState.set_market_closed(trading_date=self.get_today())

            DashboardState.update_scheduler_status(
                f"MARKET_CLEANUP_COMPLETED_RUNTIME_{runtime_count}_ACTIVE_{active_count}"
            )

            logger.info("Market cleanup completed.")

            if self.notifier:
                self.notifier.send_market_stopped_summary(
                    date_str=self.get_today(),
                    success_count=success_count,
                    failed_count=failed_count,
                )

        except Exception as ex:

            logger.exception(f"Market stop failed: {ex}")

            DashboardState.update_scheduler_status("MARKET_CLOSE_CLEANUP_FAILED")

            if self.notifier:
                self.notifier.send_critical_alert(
                    "Market Cleanup Execution",
                    str(ex),
                )

    def scheduler_cycle(self):
        """
        One scheduler cycle.
        """

        try:

            self.reset_for_new_day()

            today = self.get_today()

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            # --------------------------------------------------
            # Holiday / Weekend handling
            # --------------------------------------------------
            if not self.market_open_today:

                if not self.market_holiday_logged:

                    logger.info(f"Market holiday/weekend ({today})")
                    logger.info("Waiting for next trading day...")

                    DashboardState.set_market_holiday(
                        trading_date=today,
                        reason="NSE_TRADING_HOLIDAY_OR_WEEKEND",
                    )

                    self.market_holiday_logged = True

                    if self.notifier:
                        self.notifier.send_market_skipped(
                            date_str=today,
                            reason="NSE Trading Holiday or Weekend",
                        )

                return

            # --------------------------------------------------
            # IMPORTANT:
            # Market close cleanup must happen BEFORE the generic
            # "market already closed" return block.
            # --------------------------------------------------
            if self.market_started and self.is_market_closed_time():

                DashboardState.update_scheduler_status(
                    "MARKET_CLOSE_TIME_REACHED_STOPPING_MARKET"
                )

                self.stop_market()

                return

            # --------------------------------------------------
            # Already closed waiting state
            # --------------------------------------------------
            if self.is_market_closed_time():

                if not self.market_closed_logged:

                    logger.info("=" * 70)
                    logger.info(f"TRADING SESSION COMPLETED ({today})")
                    logger.info("Market already closed.")
                    logger.info("Waiting for next trading day...")
                    logger.info("=" * 70)

                    DashboardState.set_market_closed(
                        trading_date=today,
                    )

                    DashboardState.update_scheduler_status(
                        "TRADING_SESSION_COMPLETED_WAITING_NEXT_DAY"
                    )

                    self.market_closed_logged = True

                return

            # --------------------------------------------------
            # Daily preload
            # --------------------------------------------------
            if (
                not self.preloaded_today
                and self.market_open_today
                and self.is_preload_time()
            ):

                logger.info(f"Running preload for {today}")

                DashboardState.update_scheduler_status("PRELOAD_TIME_REACHED")

                self.perform_preload()

            # --------------------------------------------------
            # Start market feed
            # --------------------------------------------------
            if (
                self.preloaded_today
                and self.market_open_today
                and not self.market_started
                and self.is_market_open_time()
            ):

                DashboardState.update_scheduler_status("MARKET_OPEN_TIME_REACHED")

                self.start_market()

            # --------------------------------------------------
            # Waiting states
            # --------------------------------------------------
            if self.market_started:
                DashboardState.update_market_status(
                    market_status="OPEN",
                    trading_date=today,
                    preloaded_today=self.preloaded_today,
                    market_started=True,
                    market_closed_today=False,
                )

            elif self.preloaded_today:
                DashboardState.update_market_status(
                    market_status="PRELOADED_WAITING_FOR_MARKET_OPEN",
                    trading_date=today,
                    preloaded_today=True,
                    market_started=False,
                    market_closed_today=False,
                )

            else:
                DashboardState.update_market_status(
                    market_status="WAITING_FOR_PRELOAD",
                    trading_date=today,
                    preloaded_today=False,
                    market_started=False,
                    market_closed_today=False,
                )

        except Exception as ex:

            logger.exception(f"Scheduler cycle failed: {ex}")

            DashboardState.update_scheduler_status("SCHEDULER_CYCLE_FAILED")

            if self.notifier:
                self.notifier.send_critical_alert(
                    "Internal Scheduler Cycle",
                    str(ex),
                )

    def start(self):
        """
        Main scheduler loop.
        """

        logger.info("=" * 80)
        logger.info("MARKET SCHEDULER STARTED")
        logger.info("=" * 80)

        DashboardState.update_scheduler_status("MARKET_SCHEDULER_STARTED")

        MongoApp.connect()

        DashboardState.update_scheduler_status("MARKET_SCHEDULER_MONGODB_CONNECTED")

        while True:

            try:

                self.scheduler_cycle()

            except Exception as ex:

                logger.exception(f"Scheduler error: {ex}")

                DashboardState.update_scheduler_status("MAIN_SCHEDULER_LOOP_ERROR")

                if self.notifier:
                    self.notifier.send_critical_alert(
                        "Main Scheduler Thread Core Failure",
                        str(ex),
                    )

            time.sleep(Settings.SCHEDULER_SLEEP_SECONDS)
