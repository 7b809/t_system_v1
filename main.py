import signal
import sys
from datetime import datetime  # Added to capture exact date/time strings

from core.logger import get_logger
from db.mongo_app import MongoApp
from services.market_scheduler import MarketScheduler
from services.crossover_engine import CrossoverEngine
from services.preload_service import PreloadService
from services.candle_builder import CandleBuilder

# ----------------------------------------------------
# 1. New Import added
# ----------------------------------------------------
from services.telegram_service import TelegramNotificationService

logger = get_logger(__name__)


class Application:

    def __init__(self):
        # ----------------------------------------------------
        # 2. Instantiate and attach Telegram service
        # ----------------------------------------------------
        self.notifier = TelegramNotificationService()

        # Inject the notifier directly into the scheduler instance
        # so market_scheduler.py can use it for daily lifecycle alerts
        self.scheduler = MarketScheduler(notifier=self.notifier)

    def register_shutdown(self):
        """
        Graceful shutdown handling.
        """

        def shutdown_handler(signum, frame):
            try:
                logger.info("=" * 80)
                logger.info("Shutdown signal received.")

                # ----------------------------------------------------
                # 3. Notify via Telegram regarding external termination
                # ----------------------------------------------------
                signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
                self.notifier.send_critical_alert(
                    stage="OS Shutdown Signal Handler",
                    error_msg=f"Application received exit signal: {signal_name}. Forcing shutdown sequence.",
                )

                # -------------------------
                # Flush candles
                # -------------------------
                logger.info("Flushing remaining candles...")
                CrossoverEngine.flush_pending_candles()

                # -------------------------
                # Stop stream
                # -------------------------
                try:
                    if (
                        hasattr(self.scheduler, "stream_service")
                        and self.scheduler.stream_service
                    ):
                        self.scheduler.stream_service.stop()
                except Exception as ex:
                    logger.exception(f"Stream stop failed: {ex}")

                # -------------------------
                # Clear runtime
                # -------------------------
                try:
                    PreloadService.reset()
                except Exception:
                    pass

                try:
                    CandleBuilder.clear()
                except Exception:
                    pass

                # -------------------------
                # Close Mongo
                # -------------------------
                MongoApp.close()

                logger.info("Application shutdown completed.")
                logger.info("=" * 80)
                sys.exit(0)

            except Exception as ex:
                logger.exception(f"Shutdown failed: {ex}")
                # Fallback alert in case the cleanup code breaks
                self.notifier.send_critical_alert(
                    stage="Shutdown Handler Exception",
                    error_msg=f"Graceful shutdown crash: {str(ex)}",
                )
                sys.exit(1)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

    def start(self):
        """
        Application entry point.
        """
        try:
            logger.info("=" * 80)
            logger.info("UPSTOX EMA CROSSOVER ENGINE")
            logger.info("=" * 80)

            self.register_shutdown()

            MongoApp.connect()
            logger.info("MongoDB connection established.")

            # ----------------------------------------------------
            # 4. Fire initial app start confirmation telegram alert
            # ----------------------------------------------------
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.notifier.send_app_started(current_date)

            self.scheduler.start()

        except Exception as ex:
            logger.exception(f"Application failed: {ex}")
            # Send immediate alert if application core components fail to instantiate
            self.notifier.send_critical_alert(
                stage="Application Boot/Startup", error_msg=str(ex)
            )
            raise


def main():
    try:
        app = Application()
        app.start()
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received.")
    except Exception as ex:
        logger.exception(f"Fatal application error: {ex}")
        sys.exit(1)


if __name__ == "__main__":
    main()
