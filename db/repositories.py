from datetime import datetime, timezone
import threading
from db.mongo_app import MongoApp
from core.logger import get_logger

logger = get_logger(__name__)


class UpstoxRepository:
    # --- Token cache with timed refresh ---
    _ACCESS_TOKEN = None
    _LAST_REFRESH = None
    _REFRESH_INTERVAL = 300  # seconds (5 minutes) – adjust to your token expiry
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

            # Update cache
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

            # Check if we need a refresh
            if (
                cls._ACCESS_TOKEN is None
                or cls._LAST_REFRESH is None
                or (now - cls._LAST_REFRESH).total_seconds() >= cls._REFRESH_INTERVAL
            ):
                logger.info("Access token expired or missing – refreshing...")
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
        Load all strike documents.
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
                    {}, {"_id": 0, "instrument_key": 1}
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
        Fetch one strike document.
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
    def append_candle(instrument_key: str, candle: dict, trading_date: str):
        """
        Append candle into:
        candles
        daily.<date>.today_candles
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
            logger.info(
                f"Candle saved | {instrument_key} | modified={result.modified_count}"
            )
        except Exception as ex:
            logger.exception(f"Failed to save candle {instrument_key}: {ex}")

    @staticmethod
    def save_crossover(instrument_key: str, trading_date: str, crossover: dict):
        """
        Save bullish/bearish crossover.
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {"$push": {f"daily.{trading_date}.crosses_today": crossover}},
            )
            logger.info(
                f"Crossover saved | {instrument_key} | {crossover.get('signal')}"
            )
            return result
        except Exception as ex:
            logger.exception(f"Failed saving crossover {instrument_key}: {ex}")

    @staticmethod
    def save_live_crossover_by_date(
        instrument_key: str, trading_date: str, strike: str, crossover_data: dict
    ):
        """
        Saves an EMA crossover nested inside the daily.<date>.crosses_today map
        AND appends it directly to the root 'latest_crosses' array.
        """
        try:
            # MODIFIED: Atomically pushing to both daily bucket and root latest_crosses reference
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "strike": strike,
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
                f"{instrument_key} | Date: {trading_date} | Signal: {crossover_data.get('signal')}"
            )
            return result

        except Exception as ex:
            logger.exception(
                f"Failed to record crossover references for {instrument_key}: {ex}"
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
        Update current EMA values and status.
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
                    }
                },
            )
            logger.debug(f"EMA status updated | {instrument_key}")
            return result
        except Exception as ex:
            logger.exception(f"Failed updating EMA status {instrument_key}: {ex}")

    @staticmethod
    def update_last_updated(instrument_key: str):
        """
        Update document last_updated.
        """
        try:
            MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {"$set": {"last_updated": datetime.now(timezone.utc)}},
            )
        except Exception as ex:
            logger.exception(f"Failed updating last_updated {instrument_key}: {ex}")

    @staticmethod
    def ensure_daily_document(instrument_key: str, trading_date: str):
        """
        Ensure the document and daily.<date> bucket exist in the live EMA collection.
        Also handles resetting/initializing the root latest_crosses array for the new session.
        """
        try:
            # --------------------------------------------------
            # Check if the document already exists
            # --------------------------------------------------
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

                # Remove Mongo _id so MongoDB generates a new one
                master_doc.pop("_id", None)
                MongoApp.get_live_ema_collection().insert_one(master_doc)
                strike = master_doc
                logger.info(f"Created live EMA document for {instrument_key}")

            # --------------------------------------------------
            # Check if today's bucket already exists
            # --------------------------------------------------
            daily_data = strike.get("daily", {}).get(trading_date)

            if daily_data:
                return

            # --------------------------------------------------
            # Create today's daily bucket & clear root latest_crosses array for the new session day
            # --------------------------------------------------
            MongoApp.get_live_ema_collection().update_one(
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
                        # MODIFIED: Reset root latest_crosses tracking array for the new session date map
                        "latest_crosses": [],
                        "latest_crosses_date": trading_date,
                    }
                },
            )

            logger.info(
                f"Created daily bucket and initialized latest_crosses array for {trading_date} | {instrument_key}"
            )

        except Exception as ex:
            logger.exception(f"Failed creating daily bucket {instrument_key}: {ex}")
