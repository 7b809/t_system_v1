import time
import threading
import json
import asyncio

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import upstox_client

from config.settings import Settings
from core.logger import get_logger
from services.preload_service import PreloadService
from services.candle_builder import CandleBuilder
from services.crossover_engine import CrossoverEngine
from services.dashboard_state import DashboardState
from services.websocket_manager import WebSocketManager

logger = get_logger(__name__)


class UpstoxStreamService:

    def __init__(self, access_token: str):
        """
        Initialize Upstox live stream service.

        Important:
        Access token is required for live market feed subscription.
        It is not required for:
        - MongoDB operations
        - Intraday candle recovery through HistoryApi
        """

        if not access_token or not str(access_token).strip():
            DashboardState.update_scheduler_status("UPSTOX_STREAM_ACCESS_TOKEN_MISSING")

            raise ValueError(
                "Upstox access token is required for live market feed subscription."
            )

        self.access_token = str(access_token).strip()
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

        Access token is mandatory here because MarketDataStreamerV3
        is used for live market feed subscription.
        """

        try:

            if not self.access_token or not str(self.access_token).strip():
                DashboardState.update_scheduler_status("UPSTOX_STREAMER_TOKEN_MISSING")

                raise ValueError(
                    "Upstox access token is missing. "
                    "Cannot initialize live market streamer."
                )

            configuration = upstox_client.Configuration()
            configuration.access_token = self.access_token

            self.streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(configuration)
            )

            logger.info("Upstox streamer initialized.")

        except Exception as ex:

            logger.exception(f"Streamer initialization failed: {ex}")

            DashboardState.update_scheduler_status(
                "UPSTOX_STREAMER_INITIALIZATION_FAILED"
            )

            raise

    def subscribe_all_instruments(self):
        """
        Subscribe all option strike instruments plus optional NIFTY main index.

        Option strike instruments come from MongoDB/runtime state.

        NIFTY main index does not need to be stored in MongoDB.
        It is subscribed separately using:

            NIFTY_INDEX_INSTRUMENT_KEY=NSE_INDEX|Nifty 50
        """

        try:
            instrument_keys = PreloadService.get_instrument_keys()

            if not instrument_keys:
                instrument_keys = []

            # --------------------------------------------------
            # Add NIFTY main index explicitly.
            # This is not expected to exist in MongoDB option_strikes.
            # --------------------------------------------------
            nifty_index_key = getattr(Settings, "NIFTY_INDEX_INSTRUMENT_KEY", "")

            if nifty_index_key:
                nifty_index_key = str(nifty_index_key).strip()

                if nifty_index_key and nifty_index_key not in instrument_keys:
                    instrument_keys.append(nifty_index_key)

                    logger.info(
                        f"NIFTY main index added to subscription list: "
                        f"{nifty_index_key}"
                    )

            if not instrument_keys:
                logger.warning("No instrument keys available.")

                DashboardState.update_scheduler_status("NO_INSTRUMENT_KEYS_AVAILABLE")

                return

            logger.info(f"Subscribing {len(instrument_keys)} instruments.")

            self.streamer.subscribe(
                instrument_keys,
                Settings.UPSTOX_FEED_MODE,
            )

            DashboardState.update_scheduler_status(
                f"SUBSCRIBED_{len(instrument_keys)}_INSTRUMENTS"
            )

            logger.info(f"Successfully subscribed {len(instrument_keys)} instruments.")

        except Exception as ex:
            logger.exception(f"Subscription failed: {ex}")

            DashboardState.update_scheduler_status("INSTRUMENT_SUBSCRIPTION_FAILED")

            raise

    def on_open(self):
        """
        Websocket connected.
        """

        try:

            logger.info("WebSocket connected.")

            DashboardState.set_websocket_connected()

            self.subscribe_all_instruments()

        except Exception as ex:

            logger.exception(f"Open handler failed: {ex}")

            DashboardState.update_scheduler_status("WEBSOCKET_OPEN_HANDLER_FAILED")

    def _extract_ltpc(self, feed: dict):
        """
        Extract ltpc block from different Upstox feed response formats.

        Supported:
        - ltpc mode
        - fullFeed.marketFF.ltpc mode
        """

        try:

            if not feed:
                return None

            # Market quote / ltpc mode
            if "ltpc" in feed:
                return feed.get("ltpc")

            # Full feed mode
            if "fullFeed" in feed:
                return feed.get("fullFeed", {}).get("marketFF", {}).get("ltpc")

            return None

        except Exception as ex:

            logger.exception(f"Failed extracting ltpc from feed: {ex}")

            return None

    def _is_nifty_index_instrument(self, instrument_key: str):
        """
        Determine whether this instrument should be shown as NIFTY index
        in the dashboard header.

        Configure this in .env if needed:

            NIFTY_INDEX_INSTRUMENT_KEY=NSE_INDEX|Nifty 50

        If setting is missing, this returns False.
        """

        try:

            nifty_key = getattr(
                Settings,
                "NIFTY_INDEX_INSTRUMENT_KEY",
                None,
            )

            if not nifty_key:
                return False

            return instrument_key == nifty_key

        except Exception:

            return False

    def _broadcast_ltp_to_frontend(
        self,
        instrument_key: str,
        price: float,
        volume: int,
        timestamp: str,
    ):
        """
        Broadcast live LTP update to connected frontend WebSocket clients.

        Frontend clients connect through:

            /ws/ltp

        Clients can subscribe by:
        - strike + type
        - instrument_key
        - send_all=True
        """

        try:

            # Avoid async overhead if no frontend socket clients are connected.
            if WebSocketManager.get_client_count() <= 0:
                return

            runtime_state = PreloadService.get_runtime_by_key(instrument_key)

            if runtime_state:

                strike = getattr(runtime_state, "strike", "")
                option_type = getattr(runtime_state, "option_type", "")
                trading_symbol = getattr(runtime_state, "trading_symbol", "")

            else:

                strike = ""
                option_type = ""
                trading_symbol = ""

            payload = {
                "event": "ltp_update",
                "instrument_key": instrument_key,
                "strike": str(strike),
                "type": str(option_type).upper() if option_type else "",
                "option_type": str(option_type).upper() if option_type else "",
                "trading_symbol": trading_symbol,
                "ltp": price,
                "volume": volume,
                "timestamp": timestamp,
            }

            try:
                asyncio.run(WebSocketManager.broadcast_ltp(payload))

            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                try:
                    loop.run_until_complete(WebSocketManager.broadcast_ltp(payload))

                finally:
                    loop.close()

        except Exception as ex:

            logger.exception(
                f"Frontend LTP WebSocket broadcast failed | {instrument_key}: {ex}"
            )

            DashboardState.update_scheduler_status(
                "FRONTEND_LTP_SOCKET_BROADCAST_FAILED"
            )

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

                    # Save only the first instrument response
                    self.save_sample_response(
                        instrument_key,
                        feed,
                    )

                    ltpc = self._extract_ltpc(feed)

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
                    # Dashboard Tick Update
                    # -----------------------------
                    DashboardState.update_tick(
                        instrument_key=instrument_key,
                        ltp=price,
                        volume=volume,
                        timestamp=timestamp,
                    )

                    # -----------------------------
                    # Frontend WebSocket LTP Broadcast
                    # -----------------------------
                    self._broadcast_ltp_to_frontend(
                        instrument_key=instrument_key,
                        price=price,
                        volume=volume,
                        timestamp=timestamp,
                    )

                    # -----------------------------
                    # Optional NIFTY Index Update
                    # -----------------------------
                    if self._is_nifty_index_instrument(instrument_key):

                        previous_close = ltpc.get("cp")

                        change = None
                        change_percent = None

                        try:
                            if previous_close is not None:
                                previous_close = float(previous_close)

                                change = price - previous_close

                                if previous_close != 0:
                                    change_percent = (change / previous_close) * 100

                        except Exception:
                            change = None
                            change_percent = None

                        DashboardState.update_nifty_index(
                            instrument_key=instrument_key,
                            ltp=price,
                            change=change,
                            change_percent=change_percent,
                            timestamp=timestamp,
                        )
                        
                        # NIFTY main index is only for dashboard header.30
                        # # Do not build candles / EMA / crossovers for this index feed.31
                        continue

                    # -----------------------------
                    # Process Tick into Candle
                    # -----------------------------
                    completed_candle = CandleBuilder.process_tick(
                        instrument_key=instrument_key,
                        price=price,
                        volume=volume,
                        timestamp=timestamp,
                    )

                    # -----------------------------
                    # Dashboard Active Candle Count
                    # -----------------------------
                    DashboardState.update_active_candle_count(
                        CandleBuilder.get_total_active_candles()
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

                    DashboardState.update_scheduler_status("TICK_PROCESSING_FAILED")

        except Exception as ex:

            logger.exception("Message processing failed: %s", ex)

            DashboardState.update_scheduler_status(
                "WEBSOCKET_MESSAGE_PROCESSING_FAILED"
            )

    def on_error(self, error):
        """
        Websocket error callback.
        """

        logger.error(f"WebSocket error: {error}")

        DashboardState.update_scheduler_status(f"WEBSOCKET_ERROR_{str(error)[:80]}")

    def on_close(self, *args):
        """
        Websocket close callback.
        """

        logger.warning("WebSocket disconnected.")

        DashboardState.set_websocket_disconnected()

    def register_events(self):
        """
        Attach websocket events.
        """

        try:

            if not self.streamer:
                raise ValueError("Streamer is not initialized.")

            self.streamer.on("open", self.on_open)

            self.streamer.on("message", self.on_message)

            self.streamer.on("error", self.on_error)

            self.streamer.on("close", self.on_close)

        except Exception as ex:

            logger.exception(f"Event registration failed: {ex}")

            DashboardState.update_scheduler_status(
                "WEBSOCKET_EVENT_REGISTRATION_FAILED"
            )

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

            DashboardState.update_scheduler_status("CONNECTING_TO_UPSTOX_WEBSOCKET")

            self.streamer.connect()

        except Exception as ex:

            logger.exception(f"Connection failed: {ex}")

            DashboardState.set_websocket_disconnected()

            DashboardState.update_scheduler_status("UPSTOX_WEBSOCKET_CONNECTION_FAILED")

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

                DashboardState.set_websocket_connected()

                DashboardState.update_scheduler_status("UPSTOX_WEBSOCKET_CONNECTED")

                return

            except Exception as ex:

                retries += 1

                DashboardState.set_websocket_disconnected()

                DashboardState.update_scheduler_status(
                    f"WEBSOCKET_RECONNECT_ATTEMPT_{retries}"
                )

                logger.error(f"Reconnect failed | Attempt={retries} | Error={ex}")

                time.sleep(Settings.RECONNECT_DELAY)

    def start_background_stats(self):
        """
        Runtime stats logger.
        """

        def worker():

            while self.running:

                try:

                    CrossoverEngine.print_runtime_stats()

                    DashboardState.update_active_candle_count(
                        CandleBuilder.get_total_active_candles()
                    )

                except Exception as ex:

                    logger.exception(f"Stats worker failed: {ex}")

                    DashboardState.update_scheduler_status("STREAM_STATS_WORKER_FAILED")

                time.sleep(Settings.STATS_INTERVAL_SECONDS)

        self.stats_thread = threading.Thread(
            target=worker,
            daemon=True,
        )

        self.stats_thread.start()

    def stop(self):
        """
        Market close cleanup.
        """

        try:

            logger.info("Stopping Upstox stream...")

            DashboardState.update_scheduler_status("STOPPING_UPSTOX_STREAM")

            self.running = False

            if not self.streamer:

                DashboardState.set_websocket_disconnected()

                return

            try:

                instrument_keys = PreloadService.get_instrument_keys()

                if instrument_keys:

                    self.streamer.unsubscribe(instrument_keys)

                    logger.info(f"Unsubscribed {len(instrument_keys)} instruments.")

                    DashboardState.update_scheduler_status(
                        f"UNSUBSCRIBED_{len(instrument_keys)}_INSTRUMENTS"
                    )

            except Exception as ex:

                logger.exception(f"Unsubscribe failed: {ex}")

                DashboardState.update_scheduler_status("UPSTOX_UNSUBSCRIBE_FAILED")

            try:

                if hasattr(self.streamer, "disconnect"):

                    self.streamer.disconnect()

                    logger.info("WebSocket disconnected.")

            except Exception as ex:

                logger.exception(f"Disconnect failed: {ex}")

                DashboardState.update_scheduler_status(
                    "UPSTOX_WEBSOCKET_DISCONNECT_FAILED"
                )

            DashboardState.set_websocket_disconnected()

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            DashboardState.update_scheduler_status("UPSTOX_STREAM_STOPPED")

        except Exception as ex:

            logger.exception(f"Stop service failed: {ex}")

            DashboardState.update_scheduler_status("UPSTOX_STREAM_STOP_FAILED")

    def start(self):
        """
        Start service.
        """

        try:

            logger.info("=" * 80)
            logger.info("UPSTOX STREAM SERVICE STARTING")
            logger.info("=" * 80)

            if not self.access_token or not str(self.access_token).strip():
                DashboardState.update_scheduler_status(
                    "UPSTOX_STREAM_START_FAILED_TOKEN_MISSING"
                )

                raise ValueError(
                    "Upstox stream cannot start because access token is missing."
                )

            DashboardState.update_scheduler_status("UPSTOX_STREAM_SERVICE_STARTING")

            self.running = True

            self.start_background_stats()

            self.auto_reconnect()

        except Exception as ex:

            logger.exception(f"Stream startup failed: {ex}")

            self.running = False

            DashboardState.set_websocket_disconnected()

            DashboardState.update_scheduler_status("UPSTOX_STREAM_STARTUP_FAILED")

            raise
