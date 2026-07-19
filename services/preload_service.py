from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.settings import Settings
from core.logger import get_logger
from db.repositories import UpstoxRepository
from models.strike_state import StrikeState

logger = get_logger(__name__)


class PreloadService:
    """
    Loads all strike documents and builds runtime EMA state before market open
    or mid-day using snapshot array states rather than raw historical base candles.
    """

    RUNTIME_STATE = {}

    @classmethod
    def load_access_token(cls):
        """
        Load latest Upstox access token.
        """
        try:
            token = UpstoxRepository.get_access_token()
            logger.info("Access token loaded successfully.")
            return token
        except Exception as ex:
            logger.exception(f"Failed loading access token: {ex}")
            raise

    @classmethod
    def get_today(cls):
        """
        Current trading date.
        """
        return datetime.now().strftime("%Y-%m-%d")

    @classmethod
    def reset(cls):
        """
        Clear runtime cache.
        Called every market close.
        """
        try:
            count = len(cls.RUNTIME_STATE)
            cls.RUNTIME_STATE.clear()
            logger.info(f"Runtime cache cleared. Removed {count} instruments.")
        except Exception as ex:
            logger.exception(f"Failed clearing runtime cache: {ex}")

    @classmethod
    def _load_ema_state(cls, strike_doc: dict):
        """
        Extracts the runtime EMA state directly from the root 'latest_crosses'
        snapshot arrays or historical daily buckets instead of calculating over base candles.
        """
        try:
            instrument_key = strike_doc.get("instrument_key")
            latest_crosses = strike_doc.get("latest_crosses", [])

            # ----------------------------------------------------
            # Priority 1: Use the last entry from the snapshot array if it exists
            # ----------------------------------------------------
            if latest_crosses and isinstance(latest_crosses, list):
                # Grab the absolute latest crossover document state reference
                latest_cross = latest_crosses[-1]

                ema_short = latest_cross.get("ema_short")
                ema_long = latest_cross.get("ema_long")
                last_price = latest_cross.get("last_price") or latest_cross.get("close")
                signal = latest_cross.get("signal")

                if ema_short is not None and ema_long is not None:
                    relation = "ABOVE" if signal == "BULLISH" else "BELOW"
                    if last_price is None:
                        last_price = ema_short  # Emergency fallback mapping

                    logger.debug(
                        f"State resolved via root snapshot array for {instrument_key}"
                    )
                    return {
                        "ema_short": float(ema_short),
                        "ema_long": float(ema_long),
                        "last_close": float(last_price),
                        "relation": relation,
                    }

            # ----------------------------------------------------
            # Priority 2: Fall back to latest available day bucket if snapshot array is empty
            # ----------------------------------------------------
            daily = strike_doc.get("daily", {})
            if daily:
                latest_date = sorted(daily.keys())[-1]
                latest_daily = daily.get(latest_date, {})

                ema_short = latest_daily.get("ema_short")
                ema_long = latest_daily.get("ema_long")
                last_price = latest_daily.get("last_price")

                if (
                    ema_short is not None
                    and ema_long is not None
                    and last_price is not None
                ):
                    relation = "ABOVE" if ema_short > ema_long else "BELOW"
                    logger.debug(
                        f"State resolved via daily structural bucket ({latest_date}) for {instrument_key}"
                    )
                    return {
                        "ema_short": float(ema_short),
                        "ema_long": float(ema_long),
                        "last_close": float(last_price),
                        "relation": relation,
                    }

            # ----------------------------------------------------
            # Fallback 3: Hard default if the database document has no state history yet
            # ----------------------------------------------------
            logger.warning(
                f"No snapshot data or daily state found for {instrument_key}. Bootstrapping flat zero state."
            )
            return {
                "ema_short": 0.0,
                "ema_long": 0.0,
                "last_close": 0.0,
                "relation": "BELOW",
            }

        except Exception as ex:
            logger.exception(f"Failed loading EMA state from snapshot fields: {ex}")
            raise

    @classmethod
    def _process_single_strike(cls, strike_doc: dict, today: str):
        """
        Helper method to isolate processing for a single strike.
        Enables clean multi-threaded execution.
        """
        instrument_key = strike_doc.get("instrument_key")
        if not instrument_key:
            logger.warning("Instrument key missing.")
            return None, "skipped"

        # Ensure daily document tracking exists in MongoDB (Initializes today's bucket if missing)
        UpstoxRepository.ensure_daily_document(instrument_key, today)

        # Triggers clean, instantaneous snapshot status extraction
        ema_state = cls._load_ema_state(strike_doc)
        strike_state = StrikeState.from_preload(strike_doc, ema_state)

        return (instrument_key, strike_state), "loaded"

    @classmethod
    def initialize_runtime_state(cls):
        """
        Load all strike documents and build runtime cache in parallel instantly.
        """
        try:
            cls.reset()
            strikes = UpstoxRepository.get_all_strikes()

            total_loaded = 0
            total_skipped = 0
            today = cls.get_today()

            logger.info(
                f"Initializing lightning-fast runtime state for {len(strikes)} strikes via snapshots."
            )

            # With API calls completely removed from initialization, thread contention drops to near zero
            max_workers = 10

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(cls._process_single_strike, strike, today): strike
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
                            f"Failed loading {strike_doc.get('instrument_key')}: {strike_ex}"
                        )

            logger.info(
                f"Runtime initialized | Loaded={total_loaded} | Skipped={total_skipped}"
            )
            return cls.RUNTIME_STATE

        except Exception as ex:
            logger.exception(f"Runtime initialization failed: {ex}")
            raise

    @classmethod
    def get_runtime_state(cls):
        """Return complete runtime cache."""
        return cls.RUNTIME_STATE

    @classmethod
    def get_runtime_by_key(cls, instrument_key: str):
        """Return one instrument runtime state."""
        return cls.RUNTIME_STATE.get(instrument_key)

    @classmethod
    def update_runtime_state(cls, instrument_key: str, updates: dict):
        """Update StrikeState object."""
        try:
            state = cls.RUNTIME_STATE.get(instrument_key)
            if not state:
                logger.warning(f"Runtime state missing for {instrument_key}")
                return

            if "ema_short" in updates:
                state.update_ema(
                    ema_short=updates.get("ema_short", state.ema_short),
                    ema_long=updates.get("ema_long", state.ema_long),
                    last_close=updates.get("last_close", state.last_close),
                    relation=updates.get("relation", state.relation),
                )
        except Exception as ex:
            logger.exception(f"Runtime update failed {instrument_key}: {ex}")

    @classmethod
    def get_instrument_keys(cls):
        """Used for Upstox subscriptions."""
        try:
            keys = list(cls.RUNTIME_STATE.keys())
            return keys
        except Exception as ex:
            logger.exception(f"Failed loading instrument keys: {ex}")
            raise

    @classmethod
    def get_subscription_batches(cls, batch_size=None):
        """Split instruments into batches."""
        try:
            if batch_size is None:
                batch_size = Settings.SUBSCRIBE_BATCH_SIZE
            keys = cls.get_instrument_keys()
            return [keys[i : i + batch_size] for i in range(0, len(keys), batch_size)]
        except Exception as ex:
            logger.exception(f"Failed creating batches: {ex}")
            raise

    @classmethod
    def get_total_instruments(cls):
        return len(cls.RUNTIME_STATE)

    @classmethod
    def print_startup_summary(cls):
        """Startup summary."""
        try:
            total = cls.get_total_instruments()
            logger.info("=" * 70)
            logger.info(Settings.APP_NAME)
            logger.info(f"EMA SHORT : {Settings.EMA_SHORT_PERIOD}")
            logger.info(f"EMA LONG : {Settings.EMA_LONG_PERIOD}")
            logger.info(f"INSTRUMENTS : {total}")
            logger.info("=" * 70)
        except Exception as ex:
            logger.exception(f"Failed startup summary: {ex}")
