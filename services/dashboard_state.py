from datetime import datetime
from threading import RLock
from zoneinfo import ZoneInfo

from config.settings import Settings
from core.logger import get_logger
from core.datetime_utils import now


logger = get_logger(__name__)


class DashboardState:
    """
    Thread-safe in-memory dashboard state.

    This class is shared by:
    - MarketScheduler
    - PreloadService
    - UpstoxStreamService
    - CrossoverEngine
    - FastAPI dashboard API

    Purpose:
    Keep latest runtime/feed/EMA/crossover information available
    for templates/index.html through /api/dashboard.
    """

    _lock = RLock()

    # =====================================================
    # CORE STATUS
    # =====================================================

    websocket_connected = False
    market_status = "INIT"
    scheduler_status = "STARTING"

    current_trading_date = None
    last_feed_time = None
    last_update_time = None

    preloaded_today = False
    market_started = False
    market_closed_today = False

    # =====================================================
    # COUNTERS
    # =====================================================

    total_ticks = 0
    total_runtime_instruments = 0
    total_active_candles = 0

    bullish_count = 0
    bearish_count = 0

    # =====================================================
    # NIFTY INDEX DATA
    # =====================================================

    nifty_index = {
        "instrument_key": None,
        "ltp": None,
        "change": None,
        "change_percent": None,
        "last_tick_time": None,
    }

    # =====================================================
    # INSTRUMENT DATA
    # =====================================================

    instruments = {}

    # Format:
    #
    # {
    #     "NSE_FO|57360": {
    #         "instrument_key": "NSE_FO|57360",
    #         "trading_symbol": "...",
    #         "strike": "...",
    #         "option_type": "CE/PE",
    #         "ltp": 8.10,
    #         "volume": 100,
    #         "ema_short": 8.14,
    #         "ema_long": 7.45,
    #         "last_close": 8.10,
    #         "relation": "ABOVE",
    #         "signal_status": "NO_CROSSOVER",
    #         "last_tick_time": "...",
    #         "last_candle_time": "...",
    #         "last_updated": "..."
    #     }
    # }

    latest_crossovers = []

    MAX_CROSSOVERS = 50

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    @classmethod
    def _now(cls):
        """
        Current datetime string using configured timezone.
        """
        try:
            return now().isoformat()
        except Exception:
            return datetime.now().isoformat()

    @classmethod
    def _safe_float(cls, value):
        """
        Convert value to float safely.
        """
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @classmethod
    def _safe_int(cls, value):
        """
        Convert value to int safely.
        """
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    @classmethod
    def _recalculate_summary_locked(cls):
        """
        Recalculate bullish/bearish counts.

        Caller must hold _lock.
        """

        bullish = 0
        bearish = 0

        for item in cls.instruments.values():
            relation = item.get("relation")

            if relation == "ABOVE":
                bullish += 1

            elif relation == "BELOW":
                bearish += 1

        cls.bullish_count = bullish
        cls.bearish_count = bearish
        cls.total_runtime_instruments = len(cls.instruments)

    # =====================================================
    # RESET
    # =====================================================

    @classmethod
    def reset(cls):
        """
        Fully reset dashboard memory.
        Usually called only on fresh app start.
        """

        with cls._lock:
            cls.websocket_connected = False
            cls.market_status = "INIT"
            cls.scheduler_status = "STARTING"

            cls.current_trading_date = None
            cls.last_feed_time = None
            cls.last_update_time = cls._now()

            cls.preloaded_today = False
            cls.market_started = False
            cls.market_closed_today = False

            cls.total_ticks = 0
            cls.total_runtime_instruments = 0
            cls.total_active_candles = 0

            cls.bullish_count = 0
            cls.bearish_count = 0

            cls.nifty_index = {
                "instrument_key": None,
                "ltp": None,
                "change": None,
                "change_percent": None,
                "last_tick_time": None,
            }

            cls.instruments = {}
            cls.latest_crossovers = []

            logger.info("Dashboard state reset completed.")

    # =====================================================
    # SCHEDULER / MARKET STATUS
    # =====================================================

    @classmethod
    def update_scheduler_status(cls, status: str):
        """
        Update scheduler status text.
        """

        with cls._lock:
            cls.scheduler_status = status
            cls.last_update_time = cls._now()

    @classmethod
    def update_market_status(
        cls,
        market_status: str,
        trading_date: str | None = None,
        preloaded_today: bool | None = None,
        market_started: bool | None = None,
        market_closed_today: bool | None = None,
    ):
        """
        Update market/session status.
        """

        with cls._lock:
            cls.market_status = market_status

            if trading_date is not None:
                cls.current_trading_date = trading_date

            if preloaded_today is not None:
                cls.preloaded_today = bool(preloaded_today)

            if market_started is not None:
                cls.market_started = bool(market_started)

            if market_closed_today is not None:
                cls.market_closed_today = bool(market_closed_today)

            cls.last_update_time = cls._now()

    @classmethod
    def set_market_holiday(cls, trading_date: str, reason: str):
        """
        Mark market as holiday/weekend.
        """

        with cls._lock:
            cls.market_status = "HOLIDAY"
            cls.scheduler_status = reason
            cls.current_trading_date = trading_date
            cls.preloaded_today = False
            cls.market_started = False
            cls.market_closed_today = False
            cls.last_update_time = cls._now()

    @classmethod
    def set_market_closed(cls, trading_date: str):
        """
        Mark market closed.
        """

        with cls._lock:
            cls.market_status = "CLOSED"
            cls.scheduler_status = "TRADING_SESSION_COMPLETED"
            cls.current_trading_date = trading_date
            cls.market_started = False
            cls.market_closed_today = True
            cls.websocket_connected = False
            cls.last_update_time = cls._now()

    # =====================================================
    # WEBSOCKET STATUS
    # =====================================================

    @classmethod
    def set_websocket_connected(cls):
        """
        Mark websocket as connected.
        """

        with cls._lock:
            cls.websocket_connected = True
            cls.scheduler_status = "WEBSOCKET_CONNECTED"
            cls.last_update_time = cls._now()

    @classmethod
    def set_websocket_disconnected(cls):
        """
        Mark websocket as disconnected.
        """

        with cls._lock:
            cls.websocket_connected = False
            cls.scheduler_status = "WEBSOCKET_DISCONNECTED"
            cls.last_update_time = cls._now()

    # =====================================================
    # PRELOAD STATE
    # =====================================================

    @classmethod
    def load_instrument_from_preload(cls, strike_state):
        """
        Add or update one instrument after PreloadService creates StrikeState.
        """

        try:
            if not strike_state:
                return

            instrument_key = getattr(strike_state, "instrument_key", None)

            if not instrument_key:
                return

            with cls._lock:
                existing = cls.instruments.get(instrument_key, {})

                existing.update(
                    {
                        "instrument_key": instrument_key,
                        "trading_symbol": getattr(
                            strike_state,
                            "trading_symbol",
                            "",
                        ),
                        "strike": getattr(
                            strike_state,
                            "strike",
                            "",
                        ),
                        "option_type": getattr(
                            strike_state,
                            "option_type",
                            "",
                        ),
                        "ema_short": cls._safe_float(
                            getattr(strike_state, "ema_short", None)
                        ),
                        "ema_long": cls._safe_float(
                            getattr(strike_state, "ema_long", None)
                        ),
                        "last_close": cls._safe_float(
                            getattr(strike_state, "last_close", None)
                        ),
                        "relation": getattr(
                            strike_state,
                            "relation",
                            "UNKNOWN",
                        ),
                        "signal_status": existing.get(
                            "signal_status",
                            "NO_CROSSOVER",
                        ),
                        "ltp": existing.get("ltp"),
                        "volume": existing.get("volume"),
                        "last_tick_time": existing.get("last_tick_time"),
                        "last_candle_time": existing.get("last_candle_time"),
                        "last_updated": cls._now(),
                    }
                )

                cls.instruments[instrument_key] = existing

                cls._recalculate_summary_locked()

                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(f"Failed loading preload state into dashboard: {ex}")

    @classmethod
    def load_runtime_state(cls, runtime_state: dict):
        """
        Bulk load runtime state after preload completes.
        """

        try:
            with cls._lock:
                for instrument_key, strike_state in runtime_state.items():
                    existing = cls.instruments.get(instrument_key, {})

                    existing.update(
                        {
                            "instrument_key": instrument_key,
                            "trading_symbol": getattr(
                                strike_state,
                                "trading_symbol",
                                "",
                            ),
                            "strike": getattr(
                                strike_state,
                                "strike",
                                "",
                            ),
                            "option_type": getattr(
                                strike_state,
                                "option_type",
                                "",
                            ),
                            "ema_short": cls._safe_float(
                                getattr(strike_state, "ema_short", None)
                            ),
                            "ema_long": cls._safe_float(
                                getattr(strike_state, "ema_long", None)
                            ),
                            "last_close": cls._safe_float(
                                getattr(strike_state, "last_close", None)
                            ),
                            "relation": getattr(
                                strike_state,
                                "relation",
                                "UNKNOWN",
                            ),
                            "signal_status": existing.get(
                                "signal_status",
                                "NO_CROSSOVER",
                            ),
                            "ltp": existing.get("ltp"),
                            "volume": existing.get("volume"),
                            "last_tick_time": existing.get("last_tick_time"),
                            "last_candle_time": existing.get("last_candle_time"),
                            "last_updated": cls._now(),
                        }
                    )

                    cls.instruments[instrument_key] = existing

                cls.preloaded_today = True
                cls.total_runtime_instruments = len(cls.instruments)

                cls._recalculate_summary_locked()

                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(f"Failed bulk loading runtime dashboard state: {ex}")

    # =====================================================
    # LIVE TICK UPDATE
    # =====================================================

    @classmethod
    def update_tick(
        cls,
        instrument_key: str,
        ltp: float,
        volume: int | None = None,
        timestamp: str | None = None,
        trading_symbol: str | None = None,
        strike: str | None = None,
        option_type: str | None = None,
    ):
        """
        Update latest tick data for one instrument.
        Called from UpstoxStreamService.on_message().
        """

        try:
            if not instrument_key:
                return

            tick_time = timestamp or cls._now()

            with cls._lock:
                existing = cls.instruments.get(
                    instrument_key,
                    {
                        "instrument_key": instrument_key,
                        "trading_symbol": "",
                        "strike": "",
                        "option_type": "",
                        "ema_short": None,
                        "ema_long": None,
                        "last_close": None,
                        "relation": "UNKNOWN",
                        "signal_status": "NO_CROSSOVER",
                        "last_candle_time": None,
                    },
                )

                existing["ltp"] = cls._safe_float(ltp)
                existing["volume"] = cls._safe_int(volume)
                existing["last_tick_time"] = tick_time
                existing["last_updated"] = cls._now()

                if trading_symbol is not None:
                    existing["trading_symbol"] = trading_symbol

                if strike is not None:
                    existing["strike"] = strike

                if option_type is not None:
                    existing["option_type"] = option_type

                cls.instruments[instrument_key] = existing

                cls.total_ticks += 1
                cls.last_feed_time = tick_time
                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(f"Failed updating dashboard tick {instrument_key}: {ex}")

    # =====================================================
    # NIFTY INDEX UPDATE
    # =====================================================

    @classmethod
    def update_nifty_index(
        cls,
        instrument_key: str,
        ltp: float,
        change: float | None = None,
        change_percent: float | None = None,
        timestamp: str | None = None,
    ):
        """
        Update NIFTY index display data.

        This is optional. It will be used only if a NIFTY index instrument
        is subscribed and identified in Upstox feed handling.
        """

        try:
            with cls._lock:
                cls.nifty_index = {
                    "instrument_key": instrument_key,
                    "ltp": cls._safe_float(ltp),
                    "change": cls._safe_float(change),
                    "change_percent": cls._safe_float(change_percent),
                    "last_tick_time": timestamp or cls._now(),
                }

                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(f"Failed updating NIFTY index dashboard data: {ex}")

    # =====================================================
    # EMA / CANDLE UPDATE
    # =====================================================

    @classmethod
    def update_ema_state(
        cls,
        instrument_key: str,
        ema_short: float,
        ema_long: float,
        last_close: float,
        relation: str,
        signal_status: str = "NO_CROSSOVER",
        candle_timestamp: str | None = None,
    ):
        """
        Update EMA values after completed candle processing.
        Called from CrossoverEngine.process_completed_candle().
        """

        try:
            if not instrument_key:
                return

            with cls._lock:
                existing = cls.instruments.get(
                    instrument_key,
                    {
                        "instrument_key": instrument_key,
                        "trading_symbol": "",
                        "strike": "",
                        "option_type": "",
                        "ltp": None,
                        "volume": None,
                        "last_tick_time": None,
                    },
                )

                existing.update(
                    {
                        "ema_short": cls._safe_float(ema_short),
                        "ema_long": cls._safe_float(ema_long),
                        "last_close": cls._safe_float(last_close),
                        "relation": relation,
                        "signal_status": signal_status,
                        "last_candle_time": candle_timestamp,
                        "last_updated": cls._now(),
                    }
                )

                cls.instruments[instrument_key] = existing

                cls._recalculate_summary_locked()

                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(f"Failed updating dashboard EMA {instrument_key}: {ex}")

    @classmethod
    def update_active_candle_count(cls, count: int):
        """
        Update active candle count.
        """

        with cls._lock:
            cls.total_active_candles = int(count or 0)
            cls.last_update_time = cls._now()

    # =====================================================
    # CROSSOVER UPDATE
    # =====================================================

    @classmethod
    def add_crossover(
        cls,
        instrument_key: str,
        trading_date: str,
        crossover_data: dict,
        strike: str | None = None,
        trading_symbol: str | None = None,
    ):
        """
        Add latest crossover event to dashboard list.
        """

        try:
            if not instrument_key or not crossover_data:
                return

            event = {
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "strike": strike,
                "trading_symbol": trading_symbol,
                "timestamp": crossover_data.get("timestamp"),
                "signal": crossover_data.get("signal"),
                "ema_short": cls._safe_float(
                    crossover_data.get("ema_short") or crossover_data.get("short_ema")
                ),
                "ema_long": cls._safe_float(
                    crossover_data.get("ema_long") or crossover_data.get("long_ema")
                ),
                "price": cls._safe_float(
                    crossover_data.get("price")
                    or crossover_data.get("last_price")
                    or crossover_data.get("close")
                ),
                "created_at": cls._now(),
            }

            with cls._lock:
                cls.latest_crossovers.insert(0, event)
                cls.latest_crossovers = cls.latest_crossovers[: cls.MAX_CROSSOVERS]
                cls.last_update_time = cls._now()

        except Exception as ex:
            logger.exception(
                f"Failed adding dashboard crossover {instrument_key}: {ex}"
            )

    # =====================================================
    # SNAPSHOT FOR API
    # =====================================================

    @classmethod
    def get_snapshot(cls):
        """
        Return complete dashboard snapshot.

        This method is consumed by:
        GET /api/dashboard
        """

        try:
            with cls._lock:
                cls._recalculate_summary_locked()

                instruments_list = list(cls.instruments.values())

                instruments_list.sort(
                    key=lambda item: (
                        str(item.get("strike", "")),
                        str(item.get("option_type", "")),
                        str(item.get("trading_symbol", "")),
                    )
                )

                return {
                    "app": {
                        "name": Settings.APP_NAME,
                        "version": Settings.APP_VERSION,
                        "timezone": Settings.TIMEZONE,
                    },
                    "status": {
                        "websocket_connected": cls.websocket_connected,
                        "market_status": cls.market_status,
                        "scheduler_status": cls.scheduler_status,
                        "current_trading_date": cls.current_trading_date,
                        "preloaded_today": cls.preloaded_today,
                        "market_started": cls.market_started,
                        "market_closed_today": cls.market_closed_today,
                        "last_feed_time": cls.last_feed_time,
                        "last_update_time": cls.last_update_time,
                    },
                    "summary": {
                        "total_ticks": cls.total_ticks,
                        "total_runtime_instruments": cls.total_runtime_instruments,
                        "total_active_candles": cls.total_active_candles,
                        "bullish_count": cls.bullish_count,
                        "bearish_count": cls.bearish_count,
                    },
                    "nifty_index": dict(cls.nifty_index),
                    "instruments": instruments_list,
                    "latest_crossovers": list(cls.latest_crossovers),
                }

        except Exception as ex:
            logger.exception(f"Failed building dashboard snapshot: {ex}")

            return {
                "app": {
                    "name": getattr(Settings, "APP_NAME", "UPSTOX_EMA_ENGINE"),
                    "version": getattr(Settings, "APP_VERSION", "1.0.0"),
                    "timezone": getattr(Settings, "TIMEZONE", "Asia/Kolkata"),
                },
                "status": {
                    "websocket_connected": False,
                    "market_status": "ERROR",
                    "scheduler_status": "DASHBOARD_SNAPSHOT_ERROR",
                    "current_trading_date": None,
                    "preloaded_today": False,
                    "market_started": False,
                    "market_closed_today": False,
                    "last_feed_time": None,
                    "last_update_time": cls._now(),
                },
                "summary": {
                    "total_ticks": 0,
                    "total_runtime_instruments": 0,
                    "total_active_candles": 0,
                    "bullish_count": 0,
                    "bearish_count": 0,
                },
                "nifty_index": {
                    "instrument_key": None,
                    "ltp": None,
                    "change": None,
                    "change_percent": None,
                    "last_tick_time": None,
                },
                "instruments": [],
                "latest_crossovers": [],
                "error": str(ex),
            }
