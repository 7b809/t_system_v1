from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

from config.settings import Settings
from core.logger import get_logger
from db.repositories import UpstoxRepository
from models.strike_state import StrikeState
from services.intraday_recovery_service import IntradayRecoveryService
from services.dashboard_state import DashboardState

logger = get_logger(__name__)


class PreloadService:
    """
    Loads all strike documents and builds runtime EMA state before market open
    or during market hours.

    New compact MongoDB format:

    {
        "instrument_key": "...",
        "trading_symbol": "...",
        "strike": 24150,
        "type": "CE",
        "daily": {
            "YYYY-MM-DD": {
                "status": "NO_CROSSOVER",
                "total_crosses": 0,
                "crosses": []
            }
        },
        "last_updated_date": "YYYY-MM-DD",
        "last_updated": "..."
    }

    Important:
    Compact Mongo format does not persist EMA values.
    Runtime EMA values are maintained in memory.

    Intraday recovery can rebuild EMA during market hours by fetching
    intraday candles from Upstox HistoryApi.

    Access token is required only for live WebSocket feed subscription.
    """

    RUNTIME_STATE = {}
    ACCESS_TOKEN = None

    @classmethod
    def should_run_intraday_recovery(cls):
        """
        Recovery required only during market hours.

        Uses configured application timezone.
        """

        try:
            recovery_enabled = getattr(
                Settings,
                "ENABLE_INTRADAY_RECOVERY",
                True,
            )

            if not recovery_enabled:
                return False

            now = datetime.now(ZoneInfo(Settings.TIMEZONE)).time()

            return Settings.MARKET_START_TIME <= now < Settings.MARKET_END_TIME

        except Exception as ex:
            logger.exception(f"Failed checking intraday recovery window: {ex}")

            DashboardState.update_scheduler_status(
                "INTRADAY_RECOVERY_WINDOW_CHECK_FAILED"
            )

            return False

    @classmethod
    def load_access_token(cls):
        """
        Load latest Upstox access token.

        This token is required for live Upstox WebSocket feed subscription.
        It is not required for MongoDB operations or intraday candle recovery.
        """

        try:
            DashboardState.update_scheduler_status("LOADING_UPSTOX_ACCESS_TOKEN")

            token = UpstoxRepository.get_access_token()

            cls.ACCESS_TOKEN = token

            logger.info("Access token loaded into PreloadService.")

            DashboardState.update_scheduler_status("UPSTOX_ACCESS_TOKEN_LOADED")

            return token

        except Exception as ex:
            logger.exception(f"Failed loading access token: {ex}")

            DashboardState.update_scheduler_status("UPSTOX_ACCESS_TOKEN_LOAD_FAILED")

            raise

    @classmethod
    def get_today(cls):
        """
        Current trading date using configured timezone.
        """

        return datetime.now(ZoneInfo(Settings.TIMEZONE)).date().isoformat()

    @classmethod
    def reset(cls):
        """
        Clear runtime cache.
        Called every market close or before fresh preload.
        """

        try:
            count = len(cls.RUNTIME_STATE)

            cls.RUNTIME_STATE.clear()

            logger.info(f"Runtime cache cleared. Removed {count} instruments.")

            DashboardState.update_scheduler_status(
                f"RUNTIME_CACHE_CLEARED_{count}_INSTRUMENTS"
            )

        except Exception as ex:
            logger.exception(f"Failed clearing runtime cache: {ex}")

            DashboardState.update_scheduler_status("RUNTIME_CACHE_CLEAR_FAILED")

    @classmethod
    def _load_ema_state(cls, strike_doc: dict):
        """
        Load runtime EMA state.

        New compact Mongo format does not store:
        - ema_short
        - ema_long
        - last_price
        - candle_timestamp
        - latest_crosses

        So this method supports three possibilities:

        1. Optional future root runtime snapshot:
            {
                "runtime": {
                    "ema_short": 32.62,
                    "ema_long": 36.40,
                    "last_close": 29.60,
                    "relation": "BELOW"
                }
            }

        2. Backward compatibility with old existing documents:
            - latest_crosses
            - daily.<date>.ema_short
            - daily.<date>.ema_long
            - daily.<date>.last_price

        3. Fallback zero state:
            EMA starts from 0.0 and intraday recovery/live candles update it.
        """

        try:
            instrument_key = strike_doc.get("instrument_key")

            # ----------------------------------------------------
            # Priority 1: Optional future root runtime snapshot
            # ----------------------------------------------------
            runtime = strike_doc.get("runtime", {})

            if isinstance(runtime, dict):
                ema_short = runtime.get("ema_short")
                ema_long = runtime.get("ema_long")
                last_close = runtime.get("last_close")
                relation = runtime.get("relation")

                if (
                    ema_short is not None
                    and ema_long is not None
                    and last_close is not None
                    and relation
                ):
                    logger.debug(
                        f"State resolved via runtime snapshot for {instrument_key}"
                    )

                    return {
                        "ema_short": float(ema_short),
                        "ema_long": float(ema_long),
                        "last_close": float(last_close),
                        "relation": str(relation),
                    }

            # ----------------------------------------------------
            # Priority 2: Backward compatibility with old latest_crosses
            # ----------------------------------------------------
            latest_crosses = strike_doc.get("latest_crosses", [])

            if latest_crosses and isinstance(latest_crosses, list):
                latest_cross = latest_crosses[-1]

                ema_short = latest_cross.get("ema_short")
                ema_long = latest_cross.get("ema_long")

                last_price = (
                    latest_cross.get("last_price")
                    or latest_cross.get("price")
                    or latest_cross.get("close")
                )

                signal = latest_cross.get("signal")

                if ema_short is not None and ema_long is not None:
                    relation = "ABOVE" if signal == "BULLISH" else "BELOW"

                    if last_price is None:
                        last_price = ema_short

                    logger.debug(
                        f"State resolved via old latest_crosses for {instrument_key}"
                    )

                    return {
                        "ema_short": float(ema_short),
                        "ema_long": float(ema_long),
                        "last_close": float(last_price),
                        "relation": relation,
                    }

            # ----------------------------------------------------
            # Priority 3: Backward compatibility with old daily EMA fields
            # ----------------------------------------------------
            daily = strike_doc.get("daily", {})

            if daily and isinstance(daily, dict):
                for daily_date in sorted(daily.keys(), reverse=True):
                    daily_data = daily.get(daily_date, {})

                    if not isinstance(daily_data, dict):
                        continue

                    ema_short = daily_data.get("ema_short")
                    ema_long = daily_data.get("ema_long")
                    last_price = daily_data.get("last_price")

                    if (
                        ema_short is not None
                        and ema_long is not None
                        and last_price is not None
                    ):
                        relation = (
                            "ABOVE" if float(ema_short) > float(ema_long) else "BELOW"
                        )

                        logger.debug(
                            f"State resolved via old daily EMA bucket "
                            f"{daily_date} for {instrument_key}"
                        )

                        return {
                            "ema_short": float(ema_short),
                            "ema_long": float(ema_long),
                            "last_close": float(last_price),
                            "relation": relation,
                        }

            # ----------------------------------------------------
            # Fallback: compact document has no EMA snapshot
            # ----------------------------------------------------
            logger.warning(
                f"No EMA snapshot found for {instrument_key}. "
                f"Using zero EMA state. "
                f"If market is open, intraday recovery should rebuild EMA."
            )

            return {
                "ema_short": 0.0,
                "ema_long": 0.0,
                "last_close": 0.0,
                "relation": "BELOW",
            }

        except Exception as ex:
            logger.exception(f"Failed loading EMA state from compact snapshot: {ex}")

            DashboardState.update_scheduler_status("COMPACT_EMA_STATE_LOAD_FAILED")

            raise

    @classmethod
    def _process_single_strike(
        cls,
        strike_doc: dict,
        today: str,
    ):
        """
        Process one instrument.

        Steps:
        1. Ensure today's compact live EMA bucket exists.
        2. Fetch latest compact live EMA document.
        3. Load base EMA state.
        4. If market is currently open, run intraday recovery.
        5. Create StrikeState runtime object.

        Note:
        Intraday recovery does not require Upstox access token.
        """

        try:
            instrument_key = strike_doc.get("instrument_key")

            if not instrument_key:
                logger.warning("Instrument key missing.")
                return None, "skipped"

            # ----------------------------------------------------
            # Ensure compact daily document exists in live EMA collection
            # ----------------------------------------------------
            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=today,
            )

            # ----------------------------------------------------
            # Fetch compact live EMA document
            # ----------------------------------------------------
            live_doc = UpstoxRepository.get_live_ema_document(
                instrument_key=instrument_key
            )

            if live_doc:
                snapshot_doc = live_doc
            else:
                logger.warning(
                    f"Live EMA document not found for {instrument_key}. "
                    f"Falling back to master strike document."
                )

                snapshot_doc = strike_doc

            # ----------------------------------------------------
            # Base EMA snapshot
            # ----------------------------------------------------
            base_ema_state = cls._load_ema_state(snapshot_doc)

            ema_state = base_ema_state

            # ----------------------------------------------------
            # Apply intraday recovery during market hours
            # ----------------------------------------------------
            if cls.should_run_intraday_recovery():
                recovery_result = IntradayRecoveryService.recover_single_instrument(
                    strike_doc=snapshot_doc,
                    base_state=base_ema_state,
                )

                if recovery_result:
                    ema_state = recovery_result["ema_state"]

                else:
                    logger.warning(
                        f"Intraday recovery failed or unavailable for "
                        f"{instrument_key}. Using base EMA state."
                    )

                    ema_state = base_ema_state

            # ----------------------------------------------------
            # Build runtime StrikeState
            # ----------------------------------------------------
            metadata_doc = live_doc or strike_doc

            strike_state = StrikeState.from_preload(
                metadata_doc,
                ema_state,
            )

            # ----------------------------------------------------
            # Dashboard: load one instrument immediately
            # ----------------------------------------------------
            DashboardState.load_instrument_from_preload(strike_state)

            return (instrument_key, strike_state), "loaded"

        except Exception as ex:
            logger.exception(
                f"Failed processing strike {strike_doc.get('instrument_key')}: {ex}"
            )

            DashboardState.update_scheduler_status("STRIKE_PRELOAD_PROCESS_FAILED")

            return None, "skipped"

    @classmethod
    def initialize_runtime_state(cls):
        """
        Load all strike documents and build runtime cache in parallel.

        This method does not require Upstox access token.

        Token is required later when starting the live market feed.
        """

        try:
            DashboardState.update_scheduler_status("RUNTIME_INITIALIZATION_STARTING")

            cls.reset()

            strikes = UpstoxRepository.get_all_strikes()

            recovery_enabled = cls.should_run_intraday_recovery()

            if recovery_enabled:
                logger.info(
                    "Startup detected during market hours. "
                    "Intraday recovery mode enabled."
                )

                DashboardState.update_scheduler_status("INTRADAY_RECOVERY_MODE_ENABLED")

            else:
                logger.info(
                    "Startup outside active market recovery window. "
                    "Using compact Mongo snapshot state."
                )

                DashboardState.update_scheduler_status("USING_COMPACT_MONGO_STATE")

            total_loaded = 0
            total_skipped = 0

            today = cls.get_today()

            DashboardState.update_market_status(
                market_status="PRELOADING",
                trading_date=today,
                preloaded_today=False,
                market_started=False,
                market_closed_today=False,
            )

            logger.info(
                f"Initializing runtime state | "
                f"Strikes={len(strikes)} | "
                f"TradingDate={today}"
            )

            max_workers = getattr(
                Settings,
                "RECOVERY_MAX_WORKERS",
                10,
            )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        cls._process_single_strike,
                        strike,
                        today,
                    ): strike
                    for strike in strikes
                }

                for future in as_completed(futures):
                    try:
                        result, status = future.result()

                        if status == "loaded" and result:
                            inst_key, strike_state = result

                            cls.RUNTIME_STATE[inst_key] = strike_state

                            total_loaded += 1

                        else:
                            total_skipped += 1

                    except Exception as strike_ex:
                        total_skipped += 1

                        strike_doc = futures[future]

                        logger.exception(
                            f"Failed loading "
                            f"{strike_doc.get('instrument_key')}: "
                            f"{strike_ex}"
                        )

                        DashboardState.update_scheduler_status(
                            "STRIKE_PRELOAD_FUTURE_FAILED"
                        )

            logger.info(
                f"Runtime initialized | "
                f"Loaded={total_loaded} | "
                f"Skipped={total_skipped}"
            )

            # ----------------------------------------------------
            # Dashboard: bulk sync final runtime state
            # ----------------------------------------------------
            DashboardState.load_runtime_state(cls.RUNTIME_STATE)

            DashboardState.update_market_status(
                market_status="PRELOAD_COMPLETE",
                trading_date=today,
                preloaded_today=True,
                market_started=False,
                market_closed_today=False,
            )

            DashboardState.update_scheduler_status(
                f"RUNTIME_INITIALIZED_LOADED_{total_loaded}_SKIPPED_{total_skipped}"
            )

            return cls.RUNTIME_STATE

        except Exception as ex:
            logger.exception(f"Runtime initialization failed: {ex}")

            DashboardState.update_scheduler_status("RUNTIME_INITIALIZATION_FAILED")

            DashboardState.update_market_status(
                market_status="PRELOAD_FAILED",
                trading_date=cls.get_today(),
                preloaded_today=False,
                market_started=False,
                market_closed_today=False,
            )

            raise

    @classmethod
    def get_runtime_state(cls):
        """
        Return complete runtime cache.
        """

        return cls.RUNTIME_STATE

    @classmethod
    def get_runtime_by_key(
        cls,
        instrument_key: str,
    ):
        """
        Return one instrument runtime state.
        """

        return cls.RUNTIME_STATE.get(instrument_key)

    @classmethod
    def update_runtime_state(
        cls,
        instrument_key: str,
        updates: dict,
    ):
        """
        Update StrikeState object.
        """

        try:
            state = cls.RUNTIME_STATE.get(instrument_key)

            if not state:
                logger.warning(f"Runtime state missing for {instrument_key}")

                DashboardState.update_scheduler_status(
                    "RUNTIME_STATE_MISSING_FOR_UPDATE"
                )

                return

            if "ema_short" in updates:
                state.update_ema(
                    ema_short=updates.get(
                        "ema_short",
                        state.ema_short,
                    ),
                    ema_long=updates.get(
                        "ema_long",
                        state.ema_long,
                    ),
                    last_close=updates.get(
                        "last_close",
                        state.last_close,
                    ),
                    relation=updates.get(
                        "relation",
                        state.relation,
                    ),
                )

                DashboardState.load_instrument_from_preload(state)

        except Exception as ex:
            logger.exception(f"Runtime update failed {instrument_key}: {ex}")

            DashboardState.update_scheduler_status("RUNTIME_STATE_UPDATE_FAILED")

    @classmethod
    def get_instrument_keys(cls):
        """
        Used for Upstox websocket subscriptions.
        """

        try:
            return list(cls.RUNTIME_STATE.keys())

        except Exception as ex:
            logger.exception(f"Failed loading instrument keys: {ex}")

            DashboardState.update_scheduler_status(
                "RUNTIME_INSTRUMENT_KEYS_LOAD_FAILED"
            )

            raise

    @classmethod
    def get_subscription_batches(
        cls,
        batch_size=None,
    ):
        """
        Split instruments into subscription batches.
        """

        try:
            if batch_size is None:
                batch_size = Settings.SUBSCRIBE_BATCH_SIZE

            keys = cls.get_instrument_keys()

            return [
                keys[i : i + batch_size]
                for i in range(
                    0,
                    len(keys),
                    batch_size,
                )
            ]

        except Exception as ex:
            logger.exception(f"Failed creating batches: {ex}")

            DashboardState.update_scheduler_status("SUBSCRIPTION_BATCH_CREATE_FAILED")

            raise

    @classmethod
    def get_total_instruments(cls):
        """
        Runtime instrument count.
        """

        return len(cls.RUNTIME_STATE)

    @classmethod
    def print_startup_summary(cls):
        """
        Startup summary.
        """

        try:
            total = cls.get_total_instruments()

            logger.info("=" * 70)
            logger.info(Settings.APP_NAME)
            logger.info(f"EMA SHORT : {Settings.EMA_SHORT_PERIOD}")
            logger.info(f"EMA LONG  : {Settings.EMA_LONG_PERIOD}")
            logger.info(f"INSTRUMENTS : {total}")
            logger.info("=" * 70)

            DashboardState.update_scheduler_status(
                f"STARTUP_SUMMARY_PRINTED_{total}_INSTRUMENTS"
            )

        except Exception as ex:
            logger.exception(f"Failed startup summary: {ex}")

            DashboardState.update_scheduler_status("STARTUP_SUMMARY_PRINT_FAILED")
