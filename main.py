import os
import signal
import sys
import threading

from datetime import datetime
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.dashboard_api import router as dashboard_router
from config.settings import Settings
from core.logger import get_logger
from db.mongo_app import MongoApp
from services.candle_builder import CandleBuilder
from services.crossover_engine import CrossoverEngine
from services.dashboard_state import DashboardState
from services.market_scheduler import MarketScheduler
from services.preload_service import PreloadService
from services.telegram_service import TelegramNotificationService
from contextlib import asynccontextmanager


logger = get_logger(__name__)

# =====================================================
# FASTAPI APPLICATION
# =====================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI startup event triggered.")
    application.start_background()

    yield

    logger.info("FastAPI shutdown event triggered.")
    application.shutdown()

app = FastAPI(
    title=Settings.APP_NAME,
    version=Settings.APP_VERSION,
    description="UPSTOX EMA Crossover Engine Dashboard",
    lifespan=lifespan,
)

# Ensure required folders exist.
# StaticFiles fails if the static directory is missing.
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

app.include_router(dashboard_router)


class Application:
    """
    Main application bootstrap.

    Responsibilities:
    - Initialize Telegram notifier
    - Initialize market scheduler
    - Connect MongoDB
    - Register graceful shutdown
    - Start scheduler in background thread for FastAPI dashboard mode
    """

    def __init__(self):
        self.notifier = TelegramNotificationService()
        self.scheduler = MarketScheduler(notifier=self.notifier)

        self.scheduler_thread = None
        self.started = False
        self._lock = threading.RLock()

    def register_shutdown(self):
        """
        Graceful shutdown handling for OS signals.

        This is mainly useful when running:

            python main.py

        Uvicorn also has its own shutdown lifecycle, so we keep
        cleanup logic reusable through self.shutdown().
        """

        def shutdown_handler(signum, frame):
            signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"

            try:
                logger.info("=" * 80)
                logger.info(f"Shutdown signal received: {signal_name}")

                DashboardState.update_scheduler_status(
                    f"SHUTDOWN_SIGNAL_RECEIVED_{signal_name}"
                )

                self.notifier.send_critical_alert(
                    stage="OS Shutdown Signal Handler",
                    error_msg=(
                        f"Application received {signal_name}. "
                        f"Starting graceful shutdown."
                    ),
                )

                self.shutdown()

                logger.info("Application shutdown completed.")
                logger.info("=" * 80)

            except Exception as ex:
                logger.exception(f"Shutdown failed: {ex}")

                self.notifier.send_critical_alert(
                    stage="Shutdown Handler Exception",
                    error_msg=f"Graceful shutdown crash: {str(ex)}",
                )

                sys.exit(1)

        try:
            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)

        except ValueError:
            # signal.signal() only works in the main thread.
            # This can happen under some ASGI/server execution modes.
            logger.warning(
                "Signal handlers not registered because current thread "
                "is not the main thread."
            )

    def initialize(self):
        """
        Initialize core services before scheduler startup.
        """

        logger.info("=" * 80)
        logger.info("UPSTOX EMA CROSSOVER ENGINE")
        logger.info("=" * 80)

        DashboardState.update_scheduler_status("APPLICATION_INITIALIZING")

        self.register_shutdown()

        MongoApp.connect()
        logger.info("MongoDB connection established.")

        DashboardState.update_scheduler_status("MONGODB_CONNECTED")

        from core.datetime_utils import now

        current_date = now().strftime("%Y-%m-%d %H:%M:%S")

        self.notifier.send_app_started(date_str=current_date)

        DashboardState.update_market_status(
            market_status="INITIALIZED",
            trading_date=self.scheduler.get_today(),
            preloaded_today=False,
            market_started=False,
            market_closed_today=False,
        )

    def _scheduler_worker(self):
        """
        Background scheduler worker.

        MarketScheduler.start() is a blocking infinite loop,
        so it must run in a daemon thread when FastAPI dashboard is enabled.
        """

        try:
            DashboardState.update_scheduler_status("SCHEDULER_THREAD_STARTING")

            self.scheduler.start()

        except Exception as ex:
            logger.exception(f"Scheduler worker crashed: {ex}")

            DashboardState.update_scheduler_status("SCHEDULER_THREAD_CRASHED")

            self.notifier.send_critical_alert(
                stage="Market Scheduler Background Thread",
                error_msg=str(ex),
            )

    def start_background(self):
        """
        Start application in dashboard/FastAPI mode.

        This method:
        - Initializes MongoDB and notifier
        - Starts scheduler in background thread
        - Allows FastAPI to continue serving dashboard pages
        """

        with self._lock:
            if self.started:
                logger.info("Application already started. Skipping duplicate startup.")
                return

            try:
                self.initialize()

                self.scheduler_thread = threading.Thread(
                    target=self._scheduler_worker,
                    name="MarketSchedulerThread",
                    daemon=True,
                )

                self.scheduler_thread.start()

                self.started = True

                DashboardState.update_scheduler_status("SCHEDULER_RUNNING")

                logger.info("Market scheduler started in background thread.")

            except Exception as ex:
                logger.exception(f"Application startup failed: {ex}")

                DashboardState.update_scheduler_status("APPLICATION_STARTUP_FAILED")

                self.notifier.send_critical_alert(
                    stage="Application Boot/Startup",
                    error_msg=str(ex),
                )

                raise

    def start_blocking(self):
        """
        Start application in old blocking mode.

        This method is kept for compatibility, but for dashboard mode
        python main.py now starts uvicorn instead.
        """

        try:
            self.initialize()

            self.started = True

            DashboardState.update_scheduler_status("SCHEDULER_RUNNING_BLOCKING")

            self.scheduler.start()

        except Exception as ex:
            logger.exception(f"Application failed: {ex}")

            DashboardState.update_scheduler_status("APPLICATION_FAILED")

            self.notifier.send_critical_alert(
                stage="Application Boot/Startup",
                error_msg=str(ex),
            )

            raise

    def shutdown(self):
        """
        Graceful cleanup used by both:
        - OS signal handler
        - FastAPI shutdown event
        """

        try:
            DashboardState.update_scheduler_status("APPLICATION_SHUTTING_DOWN")

            logger.info("Flushing remaining candles...")
            CrossoverEngine.flush_pending_candles()

            try:
                if (
                    hasattr(self.scheduler, "stream_service")
                    and self.scheduler.stream_service
                ):
                    self.scheduler.stream_service.stop()

                    DashboardState.set_websocket_disconnected()

            except Exception as ex:
                logger.exception(f"Stream stop failed: {ex}")

            try:
                PreloadService.reset()
            except Exception as ex:
                logger.exception(f"PreloadService reset failed: {ex}")

            try:
                CandleBuilder.clear()
            except Exception as ex:
                logger.exception(f"CandleBuilder clear failed: {ex}")

            try:
                MongoApp.close()
            except Exception as ex:
                logger.exception(f"Mongo close failed: {ex}")

            DashboardState.update_market_status(
                market_status="STOPPED",
                trading_date=self.scheduler.get_today(),
                market_started=False,
                market_closed_today=True,
            )

            DashboardState.update_scheduler_status("APPLICATION_STOPPED")

            self.started = False

            logger.info("Shutdown cleanup completed.")

        except Exception as ex:
            logger.exception(f"Application shutdown cleanup failed: {ex}")

            DashboardState.update_scheduler_status("APPLICATION_SHUTDOWN_FAILED")

            self.notifier.send_critical_alert(
                stage="Application Shutdown Cleanup",
                error_msg=str(ex),
            )


# =====================================================
# GLOBAL APPLICATION INSTANCE
# =====================================================

application = Application()


# =====================================================
# FASTAPI LIFECYCLE EVENTS
# =====================================================





# =====================================================
# MAIN ENTRY POINT
# =====================================================


def main():

    try:
        host = getattr(Settings, "DASHBOARD_HOST", "0.0.0.0")
        port = int(getattr(Settings, "DASHBOARD_PORT", os.getenv("PORT", 8000)))

        logger.info("=" * 80)
        logger.info(f"Starting dashboard server on {host}:{port}")
        logger.info("=" * 80)

        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=False,
        )

    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received.")

    except Exception as ex:
        logger.exception(f"Fatal application error: {ex}")
        sys.exit(1)


if __name__ == "__main__":
    main()
