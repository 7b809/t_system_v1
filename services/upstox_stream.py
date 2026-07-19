import time
import threading

from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path

import upstox_client

from config.settings import Settings
from core.logger import get_logger
from services.preload_service import PreloadService
from services.candle_builder import CandleBuilder
from services.crossover_engine import CrossoverEngine

logger = get_logger(__name__)


class UpstoxStreamService:

    def __init__(self, access_token: str):

        self.access_token = access_token
        self.streamer = None
        self.running = False
        self.stats_thread = None
        self.sample_response_saved = False

    def save_sample_response(self, instrument_key, feed):
        """
        Save the first websocket response for reference.
        """

        try:

            if self.sample_response_saved:
                return

            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)

            file_path = logs_dir / "sample_upstox_feed.json"

            with open(file_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "instrument_key": instrument_key,
                        "feed": feed,
                    },
                    fp,
                    indent=4,
                    default=str,
                )

            self.sample_response_saved = True

            logger.info(
                "Saved sample websocket response to %s",
                file_path,
            )

        except Exception as ex:

            logger.exception(
                "Failed to save sample websocket response: %s",
                ex,
            )

    def create_streamer(self):
        """
        Create Upstox streamer.
        """

        try:

            configuration = upstox_client.Configuration()
            configuration.access_token = self.access_token

            self.streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(configuration)
            )

            logger.info("Upstox streamer initialized.")

        except Exception as ex:

            logger.exception(f"Streamer initialization failed: {ex}")
            raise

    def subscribe_all_instruments(self):
        """
        Subscribe all strike instruments.
        """

        try:

            instrument_keys = PreloadService.get_instrument_keys()

            if not instrument_keys:

                logger.warning("No instrument keys available.")
                return

            logger.info(f"Subscribing " f"{len(instrument_keys)} " f"instruments.")

            self.streamer.subscribe(instrument_keys, Settings.UPSTOX_FEED_MODE)

            logger.info(
                f"Successfully subscribed " f"{len(instrument_keys)} " f"instruments."
            )

        except Exception as ex:

            logger.exception(f"Subscription failed: {ex}")

    def on_open(self):
        """
        Websocket connected.
        """

        try:

            logger.info("WebSocket connected.")

            self.subscribe_all_instruments()

        except Exception as ex:

            logger.exception(f"Open handler failed: {ex}")

    def on_message(self, message):
        """
        Handle incoming market data.
        """

        try:

            feeds = message.get("feeds", {})

            if not feeds:
                return

            for instrument_key, feed in feeds.items():

                try:

                    ltpc = None
                    # Save only the first instrument response
                    self.save_sample_response(instrument_key, feed)
                    # Market quote mode
                    if "ltpc" in feed:
                        ltpc = feed["ltpc"]

                    # Full feed mode
                    elif "fullFeed" in feed:
                        ltpc = feed.get("fullFeed", {}).get("marketFF", {}).get("ltpc")

                    if not ltpc:
                        continue

                    # -----------------------------
                    # Price
                    # -----------------------------
                    ltp = ltpc.get("ltp")

                    if ltp is None:
                        continue

                    price = float(ltp)

                    # -----------------------------
                    # Timestamp
                    # -----------------------------
                    timestamp_raw = ltpc.get("ltt")

                    if timestamp_raw is None:
                        logger.warning(
                            "Missing timestamp for %s : %s",
                            instrument_key,
                            ltpc,
                        )
                        continue

                    logger.debug(
                        "Instrument=%s | Raw Timestamp=%s | Type=%s",
                        instrument_key,
                        timestamp_raw,
                        type(timestamp_raw).__name__,
                    )

                    timestamp = self.convert_timestamp(timestamp_raw)

                    # -----------------------------
                    # Volume
                    # -----------------------------
                    volume = int(ltpc.get("ltq", 0))

                    # -----------------------------
                    # Process Tick
                    # -----------------------------
                    completed_candle = CandleBuilder.process_tick(
                        instrument_key=instrument_key,
                        price=price,
                        volume=volume,
                        timestamp=timestamp,
                    )

                    if completed_candle:

                        CrossoverEngine.process_completed_candle(
                            instrument_key=instrument_key,
                            candle=completed_candle,
                        )

                except Exception as ex:

                    logger.exception(
                        "Tick processing failed %s: %s",
                        instrument_key,
                        ex,
                    )

        except Exception as ex:

            logger.exception("Message processing failed: %s", ex)

    def on_error(self, error):

        logger.error(f"WebSocket error: {error}")

    def on_close(self, *args):

        logger.warning("WebSocket disconnected.")

    def register_events(self):
        """
        Attach websocket events.
        """

        try:

            self.streamer.on("open", self.on_open)

            self.streamer.on("message", self.on_message)

            self.streamer.on("error", self.on_error)

            self.streamer.on("close", self.on_close)

        except Exception as ex:

            logger.exception(f"Event registration failed: {ex}")
            raise

    @staticmethod
    def convert_timestamp(timestamp) -> str:
        """
        Convert various timestamp formats to ISO-8601 string.

        Supported formats:
            - int milliseconds
            - float milliseconds
            - numeric string milliseconds
            - ISO-8601 string
            - datetime object
        """

        try:

            # --------------------------------------------------
            # Already a datetime object
            # --------------------------------------------------
            if isinstance(timestamp, datetime):

                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=ZoneInfo(Settings.TIMEZONE))

                return timestamp.astimezone(ZoneInfo(Settings.TIMEZONE)).isoformat()

            # --------------------------------------------------
            # String
            # --------------------------------------------------
            if isinstance(timestamp, str):

                timestamp = timestamp.strip()

                # Numeric timestamp string
                if timestamp.isdigit():

                    timestamp = int(timestamp)

                else:

                    # ISO timestamp string
                    return (
                        datetime.fromisoformat(timestamp)
                        .astimezone(ZoneInfo(Settings.TIMEZONE))
                        .isoformat()
                    )

            # --------------------------------------------------
            # Integer / Float milliseconds
            # --------------------------------------------------
            if isinstance(timestamp, (int, float)):

                dt = datetime.fromtimestamp(
                    timestamp / 1000,
                    tz=ZoneInfo(Settings.TIMEZONE),
                )

                return dt.isoformat()

            raise TypeError(f"Unsupported timestamp type: {type(timestamp).__name__}")

        except Exception as ex:

            logger.exception(
                "Timestamp conversion failed | value=%s | type=%s | error=%s",
                timestamp,
                type(timestamp).__name__,
                ex,
            )

            raise

    def connect(self):
        """
        Connect websocket.
        """

        try:

            self.create_streamer()

            self.register_events()

            logger.info("Connecting to Upstox...")

            self.streamer.connect()

        except Exception as ex:

            logger.exception(f"Connection failed: {ex}")
            raise

    def auto_reconnect(self):
        """
        Auto reconnect.
        """

        retries = 0

        while self.running:

            try:

                self.connect()

                logger.info("Connected successfully.")

                return

            except Exception as ex:

                retries += 1

                logger.error(
                    f"Reconnect failed " f"| Attempt={retries} " f"| Error={ex}"
                )

                time.sleep(Settings.RECONNECT_DELAY)

    def start_background_stats(self):
        """
        Runtime stats logger.
        """

        def worker():

            while self.running:

                try:

                    CrossoverEngine.print_runtime_stats()

                except Exception as ex:

                    logger.exception(f"Stats worker failed: {ex}")

                time.sleep(Settings.STATS_INTERVAL_SECONDS)

        self.stats_thread = threading.Thread(target=worker, daemon=True)

        self.stats_thread.start()

    def stop(self):
        """
        Market close cleanup.
        """

        try:

            logger.info("Stopping Upstox stream...")

            self.running = False

            if not self.streamer:
                return

            try:

                instrument_keys = PreloadService.get_instrument_keys()

                if instrument_keys:

                    self.streamer.unsubscribe(instrument_keys)

                    logger.info(
                        f"Unsubscribed " f"{len(instrument_keys)} " f"instruments."
                    )

            except Exception as ex:

                logger.exception(f"Unsubscribe failed: {ex}")

            try:

                if hasattr(self.streamer, "disconnect"):
                    self.streamer.disconnect()

                    logger.info("WebSocket disconnected.")

            except Exception as ex:

                logger.exception(f"Disconnect failed: {ex}")

        except Exception as ex:

            logger.exception(f"Stop service failed: {ex}")

    def start(self):
        """
        Start service.
        """

        try:

            logger.info("=" * 80)
            logger.info("UPSTOX STREAM SERVICE STARTING")
            logger.info("=" * 80)

            self.running = True

            self.start_background_stats()

            self.auto_reconnect()

        except Exception as ex:

            logger.exception(f"Stream startup failed: {ex}")
            raise
