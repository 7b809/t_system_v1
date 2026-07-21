from datetime import datetime, timezone
import threading

from db.mongo_app import MongoApp
from core.logger import get_logger
from config.settings import Settings

SHOW_LOGS = Settings.SHOW_LOGS_FLAG

logger = get_logger(__name__)


class UpstoxRepository:
    # --- Token cache with timed refresh ---
    _ACCESS_TOKEN = None
    _LAST_REFRESH = None
    _REFRESH_INTERVAL = 300  # seconds
    _LOCK = threading.RLock()

    @classmethod
    def _refresh_access_token(cls) -> str:
        """
        Internal method: fetch a fresh token from MongoDB and update the cache.
        Returns the new token.
        """
        try:
            token_doc = MongoApp.get_token_collection().find_one(
                {"_id": "upstox_access_token"}
            )

            if not token_doc:
                raise Exception("Upstox access token document not found.")

            access_token = token_doc.get("access_token")

            if not access_token:
                raise Exception("Access token is empty.")

            cls._ACCESS_TOKEN = access_token
            cls._LAST_REFRESH = datetime.now(timezone.utc)

            logger.info("Access token refreshed successfully.")

            return access_token

        except Exception as ex:
            logger.exception(f"Failed to refresh access token: {ex}")
            raise

    @classmethod
    def get_access_token(cls) -> str:
        """
        Fetch the Upstox access token from cache.
        If the cached token is missing or older than REFRESH_INTERVAL,
        it is refreshed from MongoDB automatically.
        """
        with cls._LOCK:
            now = datetime.now(timezone.utc)

            if (
                cls._ACCESS_TOKEN is None
                or cls._LAST_REFRESH is None
                or (now - cls._LAST_REFRESH).total_seconds() >= cls._REFRESH_INTERVAL
            ):
                logger.info("Access token expired or missing - refreshing...")
                return cls._refresh_access_token()

            logger.debug("Returning cached access token.")
            return cls._ACCESS_TOKEN

    @classmethod
    def force_refresh_access_token(cls) -> str:
        """
        Force an immediate refresh of the access token, ignoring the interval.
        """
        with cls._LOCK:
            logger.info("Forced refresh of access token.")
            return cls._refresh_access_token()

    @staticmethod
    def get_all_strikes():
        """
        Load all strike documents from master strikes collection.
        """
        try:
            strikes = list(MongoApp.get_strikes_collection().find({}))
            logger.info(f"Loaded {len(strikes)} strike documents.")
            return strikes

        except Exception as ex:
            logger.exception(f"Failed to load strikes: {ex}")
            raise

    @staticmethod
    def get_all_instruments():
        """
        Load only instrument keys.
        """
        try:
            data = list(
                MongoApp.get_strikes_collection().find(
                    {},
                    {"_id": 0, "instrument_key": 1},
                )
            )

            instrument_keys = [
                row["instrument_key"] for row in data if row.get("instrument_key")
            ]

            logger.info(f"Loaded {len(instrument_keys)} instrument keys.")

            return instrument_keys

        except Exception as ex:
            logger.exception(f"Failed to load instrument keys: {ex}")
            raise

    @staticmethod
    def get_strike_by_instrument_key(instrument_key: str):
        """
        Fetch one strike document from master strike collection.
        """
        try:
            doc = MongoApp.get_strikes_collection().find_one(
                {"instrument_key": instrument_key}
            )

            return doc

        except Exception as ex:
            logger.exception(f"Failed to fetch strike {instrument_key}: {ex}")
            raise

    @staticmethod
    def get_live_ema_document(instrument_key: str):
        """
        Fetch live EMA document from live_ema_analysis collection.

        This is used during preload/recovery so the base EMA state
        comes from the latest live EMA document, not only from the
        master option_strikes document.
        """
        try:
            return MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key}
            )

        except Exception as ex:
            logger.exception(f"Failed loading live EMA document {instrument_key}: {ex}")
            return None

    @staticmethod
    def append_candle(
        instrument_key: str,
        candle: dict,
        trading_date: str,
    ):
        """
        Append candle into:
        - candles
        - daily.<date>.today_candles
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$push": {
                        "candles": candle,
                        f"daily.{trading_date}.today_candles": candle,
                    }
                },
            )

            if SHOW_LOGS:
                logger.info(
                f"Candle saved | {instrument_key} | "
                f"modified={result.modified_count}"
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed to save candle {instrument_key}: {ex}")
            return None

    @staticmethod
    def save_crossover(
        instrument_key: str,
        trading_date: str,
        crossover: dict,
    ):
        """
        Save bullish/bearish crossover.
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {"$push": {f"daily.{trading_date}.crosses_today": crossover}},
            )

            logger.info(
                f"Crossover saved | "
                f"{instrument_key} | "
                f"{crossover.get('signal')}"
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed saving crossover {instrument_key}: {ex}")
            return None

    @staticmethod
    def save_live_crossover_by_date(
        instrument_key: str,
        trading_date: str,
        strike: str,
        crossover_data: dict,
    ):
        """
        Saves an EMA crossover nested inside:
        - daily.<date>.crosses_today

        Also appends it directly to:
        - latest_crosses
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "strike": strike,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                        "latest_crosses_date": trading_date,
                    },
                    "$push": {
                        f"daily.{trading_date}.crosses_today": crossover_data,
                        "latest_crosses": crossover_data,
                    },
                },
                upsert=True,
            )

            logger.info(
                f"Structured crossover saved into history and latest_crosses | "
                f"{instrument_key} | "
                f"Date={trading_date} | "
                f"Signal={crossover_data.get('signal')}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed to record crossover references for " f"{instrument_key}: {ex}"
            )
            raise

    @staticmethod
    def update_live_ema_status(
        instrument_key: str,
        trading_date: str,
        signal_status: str,
        ema_short: float,
        ema_long: float,
        last_price: float,
        candle_timestamp: str,
    ):
        """
        Update current EMA values and status during live streaming.
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}.signal_status": signal_status,
                        f"daily.{trading_date}.ema_short": ema_short,
                        f"daily.{trading_date}.ema_long": ema_long,
                        f"daily.{trading_date}.last_price": last_price,
                        f"daily.{trading_date}.candle_timestamp": candle_timestamp,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            logger.debug(f"EMA status updated | {instrument_key}")

            return result

        except Exception as ex:
            logger.exception(f"Failed updating EMA status {instrument_key}: {ex}")
            return None

    @staticmethod
    def update_last_updated(instrument_key: str):
        """
        Update root document last_updated timestamp.
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {"$set": {"last_updated": datetime.now(timezone.utc)}},
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed updating last_updated {instrument_key}: {ex}")
            return None

    @staticmethod
    def ensure_daily_document(
        instrument_key: str,
        trading_date: str,
    ):
        """
        Ensure the live EMA document and daily.<date> bucket exist.

        If the instrument does not exist in live EMA collection,
        copy the master strike document from option_strikes.

        If the current date bucket does not exist,
        create it and reset latest_crosses for the session.
        """
        try:
            strike = MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key}
            )

            # --------------------------------------------------
            # First time: copy master document into live collection
            # --------------------------------------------------
            if not strike:
                master_doc = MongoApp.get_strikes_collection().find_one(
                    {"instrument_key": instrument_key}
                )

                if not master_doc:
                    raise Exception(
                        f"Master strike document not found: {instrument_key}"
                    )

                master_doc.pop("_id", None)

                MongoApp.get_live_ema_collection().insert_one(master_doc)

                strike = master_doc

                logger.info(f"Created live EMA document for {instrument_key}")

            # --------------------------------------------------
            # If today's bucket already exists, nothing to do
            # --------------------------------------------------
            daily_data = strike.get("daily", {}).get(trading_date)

            if daily_data:
                return

            # --------------------------------------------------
            # Create today's daily bucket
            # --------------------------------------------------
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}": {
                            "signal": None,
                            "signal_status": "NO_CROSSOVER",
                            "crosses_today": [],
                            "today_candles": [],
                            "ema_short": None,
                            "ema_long": None,
                            "last_price": None,
                            "candle_timestamp": None,
                        },
                        "latest_crosses": [],
                        "latest_crosses_date": trading_date,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            logger.info(
                f"Created daily bucket and initialized latest_crosses array | "
                f"{trading_date} | {instrument_key}"
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed creating daily bucket {instrument_key}: {ex}")
            return None

    @staticmethod
    def get_current_day_state(
        instrument_key: str,
        trading_date: str,
    ):
        """
        Returns current day's EMA state and last processed candle timestamp.
        """
        try:
            doc = MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key},
                {
                    "_id": 0,
                    f"daily.{trading_date}": 1,
                },
            )

            if not doc:
                return None

            return doc.get("daily", {}).get(trading_date)

        except Exception as ex:
            logger.exception(f"Failed loading day state {instrument_key}: {ex}")
            return None

    @staticmethod
    def get_last_processed_timestamp(
        instrument_key: str,
        trading_date: str,
    ):
        """
        Returns latest processed candle timestamp for the given instrument/date.
        """
        try:
            state = UpstoxRepository.get_current_day_state(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            if not state:
                return None

            return state.get("candle_timestamp")

        except Exception as ex:
            logger.exception(f"Failed getting candle timestamp {instrument_key}: {ex}")
            return None

    @staticmethod
    def save_recovered_crossovers(
        instrument_key: str,
        trading_date: str,
        crossovers: list,
    ):
        """
        Save recovered crossover events.

        Prevents duplicate inserts by checking crossover timestamps
        already stored in daily.<date>.crosses_today.
        """
        try:
            if not crossovers:
                return 0

            new_crossovers = []

            for crossover in crossovers:
                timestamp = crossover.get("timestamp")

                if not timestamp:
                    continue

                exists = UpstoxRepository.crossover_exists(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    timestamp=timestamp,
                )

                if not exists:
                    new_crossovers.append(crossover)

            if not new_crossovers:
                logger.info(f"No new recovered crossovers to save | {instrument_key}")
                return 0

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                        "latest_crosses_date": trading_date,
                    },
                    "$push": {
                        f"daily.{trading_date}.crosses_today": {
                            "$each": new_crossovers
                        },
                        "latest_crosses": {"$each": new_crossovers},
                    },
                },
            )

            logger.info(
                f"Recovered crossovers saved | "
                f"{instrument_key} | "
                f"Inserted={len(new_crossovers)}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed saving recovered crossovers {instrument_key}: {ex}"
            )
            return None

    @staticmethod
    def crossover_exists(
        instrument_key: str,
        trading_date: str,
        timestamp: str,
    ):
        """
        Check whether crossover already exists for the given timestamp.
        """
        try:
            doc = MongoApp.get_live_ema_collection().find_one(
                {
                    "instrument_key": instrument_key,
                    f"daily.{trading_date}.crosses_today.timestamp": timestamp,
                },
                {"_id": 1},
            )

            return doc is not None

        except Exception as ex:
            logger.exception(f"Crossover lookup failed: {ex}")
            return False

    @staticmethod
    def update_recovered_ema_state(
        instrument_key: str,
        trading_date: str,
        ema_short: float,
        ema_long: float,
        last_price: float,
        relation: str,
        candle_timestamp: str,
    ):
        """
        Save recovered EMA state after startup intraday recovery.

        relation should normally be:
        - ABOVE
        - BELOW
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}.signal_status": relation,
                        f"daily.{trading_date}.ema_short": ema_short,
                        f"daily.{trading_date}.ema_long": ema_long,
                        f"daily.{trading_date}.last_price": last_price,
                        f"daily.{trading_date}.candle_timestamp": candle_timestamp,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            logger.info(
                f"Recovered EMA state saved | "
                f"{instrument_key} | "
                f"Date={trading_date} | "
                f"EMA9={ema_short:.6f} | "
                f"EMA21={ema_long:.6f} | "
                f"Relation={relation}"
            )

            if result.modified_count == 0:
                logger.warning(
                    f"Recovered EMA update did not modify document | "
                    f"{instrument_key} | Date={trading_date}"
                )

            return result

        except Exception as ex:
            logger.exception(f"Failed saving recovered EMA {instrument_key}: {ex}")
            return None
