from datetime import datetime, timezone
import threading
import json
import os
import tempfile
from pathlib import Path

from db.mongo_app import MongoApp
from core.logger import get_logger
from config.settings import Settings
from core.datetime_utils import utc_now

SHOW_LOGS = Settings.SHOW_LOGS_FLAG

logger = get_logger(__name__)


class UpstoxRepository:
    # --- Token cache with timed refresh ---
    _ACCESS_TOKEN = None
    _LAST_REFRESH = None
    _REFRESH_INTERVAL = 300  # seconds
    _LOCK = threading.RLock()

    # --- JSON persistence ---
    _JSON_LOCK = threading.RLock()
    _JSON_DIR = Path("data/crossovers")

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
            cls._LAST_REFRESH = utc_now()

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
            now = utc_now()

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
            logger.exception(f"Failed pruning old daily buckets {instrument_key}: {ex}")

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
    # JSON PERSISTENCE HELPERS
    # =====================================================

    @classmethod
    def _ensure_json_dir(cls) -> None:
        """Create the JSON storage directory if it doesn't exist."""
        try:
            cls._JSON_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as ex:
            logger.exception(f"Failed to create JSON directory: {ex}")
            raise

    @classmethod
    def _get_json_path(cls, trading_date: str) -> Path:
        """Return the file path for a given trading date."""
        return cls._JSON_DIR / f"{trading_date}.json"

    @classmethod
    def _read_json_file(cls, trading_date: str) -> dict:
        """
        Read the JSON file for the given date.
        Returns a dict mapping instrument_key to its data.
        If file doesn't exist or is malformed, returns empty dict.
        """
        file_path = cls._get_json_path(trading_date)
        if not file_path.exists():
            return {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                else:
                    logger.warning(
                        f"JSON file {file_path} does not contain a dict; resetting."
                    )
                    return {}
        except json.JSONDecodeError:
            logger.warning(f"JSON file {file_path} is malformed; resetting.")
            return {}
        except Exception as ex:
            logger.exception(f"Error reading JSON file {file_path}: {ex}")
            return {}

    @classmethod
    def _write_json_atomic(cls, trading_date: str, data: dict) -> None:
        """
        Write the data to the JSON file atomically (using a temporary file).
        Thread-safe via class-level lock.
        """
        with cls._JSON_LOCK:
            cls._ensure_json_dir()
            file_path = cls._get_json_path(trading_date)

            # Write to a temporary file in the same directory
            temp_file = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(file_path.parent),
                prefix=f".{file_path.name}.tmp",
                delete=False,
            )

            try:
                json.dump(data, temp_file, indent=2, default=str)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_file.close()

                # Atomic replace
                os.replace(temp_file.name, file_path)

                # Log when a new file is created (i.e., it didn't exist before)
                if not file_path.exists():
                    logger.info(f"JSON crossover file created: {file_path}")

            except Exception as ex:
                # Clean up the temp file if something goes wrong
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass
                logger.exception(f"Failed to write JSON file {file_path}: {ex}")
                raise

    @classmethod
    def _update_json_crossover(
        cls,
        instrument_key: str,
        trading_date: str,
        crossover: dict,
    ) -> None:
        """
        Update the JSON file with a new crossover for the given instrument.
        This method reads the current file, updates the instrument's data,
        and writes back atomically.
        """
        with cls._JSON_LOCK:
            data = cls._read_json_file(trading_date)

            # If the instrument is not yet in the file, create a new entry.
            if instrument_key not in data:
                # Fetch master strike document to get details.
                master_doc = cls.get_strike_by_instrument_key(instrument_key)
                if not master_doc:
                    logger.error(
                        f"Cannot add instrument {instrument_key} to JSON: master strike not found."
                    )
                    return

                new_entry = {
                    "instrument_key": master_doc.get("instrument_key"),
                    "trading_symbol": master_doc.get("trading_symbol", ""),
                    "strike": master_doc.get("strike"),
                    "type": master_doc.get("type"),  # CE/PE
                    "status": "NO_CROSSOVER",
                    "total_crosses": 0,
                    "crossovers": [],
                    "last_updated": utc_now().isoformat(),
                }
                data[instrument_key] = new_entry
                logger.info(
                    f"Added new instrument to JSON crossover file: {instrument_key}"
                )

            # Get the entry and update it.
            entry = data[instrument_key]

            # Append the new crossover (use compact format).
            compact_crossover = cls._clean_crossover(crossover)
            if not compact_crossover:
                logger.warning(
                    f"Empty crossover not saved to JSON for {instrument_key}"
                )
                return

            # Ensure timestamp is present; skip if not.
            if not compact_crossover.get("timestamp"):
                logger.warning(
                    f"Crossover without timestamp skipped for JSON: {instrument_key}"
                )
                return

            # Avoid duplicate crossovers (same timestamp).
            existing_timestamps = {c.get("timestamp") for c in entry["crossovers"]}
            if compact_crossover["timestamp"] in existing_timestamps:
                logger.debug(
                    f"Duplicate crossover skipped for JSON: {instrument_key} "
                    f"timestamp={compact_crossover['timestamp']}"
                )
                return

            entry["crossovers"].append(compact_crossover)
            entry["total_crosses"] = len(entry["crossovers"])
            # Update status to the signal of the latest crossover.
            entry["status"] = compact_crossover.get("signal", "NO_CROSSOVER")
            entry["last_updated"] = utc_now().isoformat()

            # Write back atomically.
            cls._write_json_atomic(trading_date, data)

            logger.info(
                f"JSON crossover appended for {instrument_key} | "
                f"Date={trading_date} | "
                f"Signal={entry['status']} | "
                f"Total={entry['total_crosses']}"
            )

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
                    "last_updated": utc_now(),
                }

                MongoApp.get_live_ema_collection().insert_one(compact_doc)

                logger.info(f"Created compact live EMA document | {instrument_key}")

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
                        "last_updated": utc_now(),
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
                        "last_updated": utc_now(),
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
                        "last_updated": utc_now(),
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

            # --- JSON persistence: update after successful MongoDB save ---
            UpstoxRepository._update_json_crossover(
                instrument_key=instrument_key,
                trading_date=trading_date,
                crossover=compact_crossover,
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
                        "last_updated": utc_now(),
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

            # --- JSON persistence: update for each new crossover ---
            for crossover in new_crossovers:
                UpstoxRepository._update_json_crossover(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    crossover=crossover,
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
                        "last_updated": utc_now(),
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
                        "last_updated": utc_now(),
                    }
                },
            )

            return result

        except Exception as ex:
            logger.exception(f"Failed updating last_updated {instrument_key}: {ex}")
            return None
