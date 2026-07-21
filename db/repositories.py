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

    # =====================================================
    # ACCESS TOKEN METHODS
    # =====================================================

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

    # =====================================================
    # MASTER STRIKE FETCH METHODS
    # =====================================================

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

    # =====================================================
    # LIVE EMA DOCUMENT FETCH
    # =====================================================

    @staticmethod
    def get_live_ema_document(instrument_key: str):
        """
        Fetch compact live EMA document from live_ema_analysis collection.
        """
        try:
            return MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key}
            )

        except Exception as ex:
            logger.exception(f"Failed loading live EMA document {instrument_key}: {ex}")
            return None

    # =====================================================
    # INTERNAL HELPERS FOR COMPACT DOC FORMAT
    # =====================================================

    @staticmethod
    def _clean_crossover(crossover: dict) -> dict:
        """
        Convert internal crossover object into compact Mongo format.

        Stored crossover format:

        {
            "timestamp": "...",
            "signal": "BULLISH/BEARISH",
            "price": 121.40
        }

        EMA values are intentionally not persisted in MongoDB.
        """

        try:
            if not crossover:
                return {}

            return {
                "timestamp": crossover.get("timestamp"),
                "signal": crossover.get("signal"),
                "price": (
                    crossover.get("price")
                    or crossover.get("last_price")
                    or crossover.get("close")
                ),
            }

        except Exception as ex:
            logger.exception(f"Failed cleaning crossover: {ex}")
            return {}

    @staticmethod
    def _keep_last_5_daily_buckets(instrument_key: str):
        """
        Keep only latest 5 date buckets inside daily.

        Example:

        daily: {
            2026-07-17,
            2026-07-18,
            2026-07-19,
            2026-07-20,
            2026-07-21
        }

        If more than 5 dates exist, older dates are removed.
        """

        try:
            doc = MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key},
                {"daily": 1},
            )

            if not doc:
                return

            daily = doc.get("daily", {})

            if not isinstance(daily, dict):
                return

            dates = sorted(daily.keys())

            if len(dates) <= 5:
                return

            old_dates = dates[:-5]

            unset_fields = {f"daily.{date_key}": "" for date_key in old_dates}

            if unset_fields:
                MongoApp.get_live_ema_collection().update_one(
                    {"instrument_key": instrument_key},
                    {"$unset": unset_fields},
                )

                logger.info(
                    f"Old daily buckets pruned | "
                    f"{instrument_key} | Removed={old_dates}"
                )

        except Exception as ex:
            logger.exception(
                f"Failed pruning old daily buckets {instrument_key}: {ex}"
            )

    @staticmethod
    def _get_compact_status(signal_status: str | None) -> str:
        """
        Normalize status value for compact daily format.

        Allowed values:
        - BULLISH
        - BEARISH
        - NO_CROSSOVER
        - ABOVE
        - BELOW

        For relation values:
        ABOVE remains ABOVE for dashboard/runtime compatibility if passed.
        BELOW remains BELOW.
        """

        try:
            if not signal_status:
                return "NO_CROSSOVER"

            value = str(signal_status).strip().upper()

            if value in {"BULLISH", "BEARISH", "NO_CROSSOVER", "ABOVE", "BELOW"}:
                return value

            return "NO_CROSSOVER"

        except Exception:
            return "NO_CROSSOVER"

    # =====================================================
    # CANDLE STORAGE - DISABLED FOR NEW FORMAT
    # =====================================================

    @staticmethod
    def append_candle(
        instrument_key: str,
        candle: dict,
        trading_date: str,
    ):
        """
        Candle storage disabled.

        New compact Mongo format does not store:
        - root candles
        - daily.<date>.today_candles

        This method is intentionally kept as no-op so existing callers
        do not break.
        """

        if SHOW_LOGS:
            logger.debug(
                f"Candle storage skipped by compact format | "
                f"{instrument_key} | Date={trading_date}"
            )

        return None

    # =====================================================
    # DAILY DOCUMENT ENSURE
    # =====================================================

    @staticmethod
    def ensure_daily_document(
        instrument_key: str,
        trading_date: str,
    ):
        """
        Ensure compact live EMA document and today's daily bucket exist.

        New daily format:

        daily.<date> = {
            "status": "NO_CROSSOVER",
            "total_crosses": 0,
            "crosses": []
        }

        Also keeps only latest 5 daily buckets.
        """

        try:
            live_doc = MongoApp.get_live_ema_collection().find_one(
                {"instrument_key": instrument_key}
            )

            # --------------------------------------------------
            # First time: create compact live document from master strike
            # --------------------------------------------------
            if not live_doc:
                master_doc = MongoApp.get_strikes_collection().find_one(
                    {"instrument_key": instrument_key}
                )

                if not master_doc:
                    raise Exception(
                        f"Master strike document not found: {instrument_key}"
                    )

                compact_doc = {
                    "instrument_key": master_doc.get("instrument_key"),
                    "trading_symbol": master_doc.get("trading_symbol", ""),
                    "strike": master_doc.get("strike"),
                    "type": master_doc.get("type"),
                    "daily": {
                        trading_date: {
                            "status": "NO_CROSSOVER",
                            "total_crosses": 0,
                            "crosses": [],
                        }
                    },
                    "last_updated_date": trading_date,
                    "last_updated": datetime.now(timezone.utc),
                }

                MongoApp.get_live_ema_collection().insert_one(compact_doc)

                logger.info(
                    f"Created compact live EMA document | {instrument_key}"
                )

                return compact_doc

            # --------------------------------------------------
            # Existing document: ensure today's bucket exists
            # --------------------------------------------------
            daily = live_doc.get("daily", {})

            if not isinstance(daily, dict):
                daily = {}

            daily_data = daily.get(trading_date)

            if daily_data:
                UpstoxRepository._keep_last_5_daily_buckets(instrument_key)
                return live_doc

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}": {
                            "status": "NO_CROSSOVER",
                            "total_crosses": 0,
                            "crosses": [],
                        },
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            UpstoxRepository._keep_last_5_daily_buckets(instrument_key)

            logger.info(
                f"Created compact daily bucket | "
                f"{instrument_key} | Date={trading_date}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed creating compact daily bucket {instrument_key}: {ex}"
            )
            return None

    # =====================================================
    # STATUS UPDATE
    # =====================================================

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
        Update compact daily status only.

        New format does NOT save:
        - ema_short
        - ema_long
        - last_price
        - candle_timestamp

        It only updates:
        - daily.<date>.status
        - last_updated
        - last_updated_date
        """

        try:
            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            compact_status = UpstoxRepository._get_compact_status(signal_status)

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}.status": compact_status,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            UpstoxRepository._keep_last_5_daily_buckets(instrument_key)

            logger.debug(
                f"Compact status updated | "
                f"{instrument_key} | Date={trading_date} | Status={compact_status}"
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed updating compact status {instrument_key}: {ex}")
            return None

    # =====================================================
    # CROSSOVER SAVE METHODS
    # =====================================================

    @staticmethod
    def save_crossover(
        instrument_key: str,
        trading_date: str,
        crossover: dict,
    ):
        """
        Compatibility wrapper for saving crossover.

        Saves into:
        daily.<date>.crosses

        Updates:
        daily.<date>.total_crosses
        daily.<date>.status
        """

        try:
            return UpstoxRepository.save_live_crossover_by_date(
                instrument_key=instrument_key,
                trading_date=trading_date,
                strike="",
                crossover_data=crossover,
            )

        except Exception as ex:
            logger.exception(f"Failed saving compact crossover {instrument_key}: {ex}")
            return None

    @staticmethod
    def save_live_crossover_by_date(
        instrument_key: str,
        trading_date: str,
        strike: str,
        crossover_data: dict,
    ):
        """
        Save live crossover into compact document format.

        New storage path:

        daily.<date>.crosses[]

        Also updates:

        daily.<date>.total_crosses
        daily.<date>.status
        last_updated
        last_updated_date
        """

        try:
            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            compact_crossover = UpstoxRepository._clean_crossover(crossover_data)

            if not compact_crossover:
                logger.warning(
                    f"Empty crossover skipped | {instrument_key} | {trading_date}"
                )
                return None

            timestamp = compact_crossover.get("timestamp")

            if not timestamp:
                logger.warning(
                    f"Crossover without timestamp skipped | {instrument_key}"
                )
                return None

            exists = UpstoxRepository.crossover_exists(
                instrument_key=instrument_key,
                trading_date=trading_date,
                timestamp=timestamp,
            )

            if exists:
                logger.info(
                    f"Duplicate crossover skipped | "
                    f"{instrument_key} | Date={trading_date} | Timestamp={timestamp}"
                )
                return None

            signal = compact_crossover.get("signal") or "NO_CROSSOVER"

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "strike": strike,
                        f"daily.{trading_date}.status": signal,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    },
                    "$push": {
                        f"daily.{trading_date}.crosses": compact_crossover,
                    },
                    "$inc": {
                        f"daily.{trading_date}.total_crosses": 1,
                    },
                },
                upsert=True,
            )

            UpstoxRepository._keep_last_5_daily_buckets(instrument_key)

            logger.info(
                f"Compact crossover saved | "
                f"{instrument_key} | "
                f"Date={trading_date} | "
                f"Signal={signal}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed saving compact crossover for {instrument_key}: {ex}"
            )
            raise

    @staticmethod
    def save_recovered_crossovers(
        instrument_key: str,
        trading_date: str,
        crossovers: list,
    ):
        """
        Save recovered crossover events into compact daily format.

        Prevents duplicate inserts by checking crossover timestamp already
        stored in:

        daily.<date>.crosses.timestamp
        """

        try:
            if not crossovers:
                return 0

            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            new_crossovers = []

            for crossover in crossovers:
                compact = UpstoxRepository._clean_crossover(crossover)

                timestamp = compact.get("timestamp")

                if not timestamp:
                    continue

                exists = UpstoxRepository.crossover_exists(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    timestamp=timestamp,
                )

                if not exists:
                    new_crossovers.append(compact)

            if not new_crossovers:
                logger.info(
                    f"No new recovered compact crossovers to save | {instrument_key}"
                )
                return 0

            last_signal = new_crossovers[-1].get("signal", "NO_CROSSOVER")

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        f"daily.{trading_date}.status": last_signal,
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    },
                    "$push": {
                        f"daily.{trading_date}.crosses": {
                            "$each": new_crossovers,
                        },
                    },
                    "$inc": {
                        f"daily.{trading_date}.total_crosses": len(new_crossovers),
                    },
                },
            )

            UpstoxRepository._keep_last_5_daily_buckets(instrument_key)

            logger.info(
                f"Recovered compact crossovers saved | "
                f"{instrument_key} | "
                f"Inserted={len(new_crossovers)}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed saving recovered compact crossovers {instrument_key}: {ex}"
            )
            return None

    @staticmethod
    def crossover_exists(
        instrument_key: str,
        trading_date: str,
        timestamp: str,
    ):
        """
        Check whether crossover already exists in compact format.

        New path:

        daily.<date>.crosses.timestamp
        """

        try:
            doc = MongoApp.get_live_ema_collection().find_one(
                {
                    "instrument_key": instrument_key,
                    f"daily.{trading_date}.crosses.timestamp": timestamp,
                },
                {"_id": 1},
            )

            return doc is not None

        except Exception as ex:
            logger.exception(f"Compact crossover lookup failed: {ex}")
            return False

    # =====================================================
    # CURRENT DAY STATE
    # =====================================================

    @staticmethod
    def get_current_day_state(
        instrument_key: str,
        trading_date: str,
    ):
        """
        Returns current compact daily state.

        Expected return:

        {
            "status": "NO_CROSSOVER",
            "total_crosses": 0,
            "crosses": []
        }
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
            logger.exception(f"Failed loading compact day state {instrument_key}: {ex}")
            return None

    @staticmethod
    def get_last_processed_timestamp(
        instrument_key: str,
        trading_date: str,
    ):
        """
        New compact Mongo format does not store candle_timestamp.

        Returning None means intraday recovery will replay available
        intraday candles from Upstox HistoryApi.

        If you later add root runtime.last_candle_timestamp,
        this method can read it from there.
        """

        return None

    # =====================================================
    # RECOVERED EMA STATE - NO EMA PERSISTENCE
    # =====================================================

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
        EMA values are no longer persisted in MongoDB.

        This method only:
        - ensures today's compact daily bucket exists
        - updates last_updated
        - updates last_updated_date

        Runtime EMA values remain in memory.
        """

        try:
            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "last_updated": datetime.now(timezone.utc),
                        "last_updated_date": trading_date,
                    }
                },
            )

            logger.info(
                f"Recovered EMA runtime processed without Mongo EMA persistence | "
                f"{instrument_key} | Date={trading_date} | "
                f"EMA9={ema_short:.6f} | EMA21={ema_long:.6f} | "
                f"Relation={relation}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Failed updating recovered compact metadata {instrument_key}: {ex}"
            )
            return None

    # =====================================================
    # LAST UPDATED
    # =====================================================

    @staticmethod
    def update_last_updated(instrument_key: str):
        """
        Update root document last_updated timestamp.
        """
        try:
            result = MongoApp.get_live_ema_collection().update_one(
                {"instrument_key": instrument_key},
                {
                    "$set": {
                        "last_updated": datetime.now(timezone.utc),
                    }
                },
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed updating last_updated {instrument_key}: {ex}")
            return None