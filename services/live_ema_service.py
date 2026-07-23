# services/live_ema_service.py

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.db import live_ema_coll
from core.logger import get_logger
from core.time_utils import get_ist_now

logger = get_logger("live_ema_service")


class LiveEMAService:
    """
    Handles MongoDB operations for the 'live_ema_analysis' collection.
    Manages daily pre-market document resets and stores live/recovery 1-minute EMA crossover updates.
    """

    def _convert_date_format(self, date_str: str) -> str:
        """
        Converts 'YYYY-MM-DD' to 'DD-MM-YYYY' format for dynamic key mapping under 'daily'.
        If already 'DD-MM-YYYY', returns as is.
        """
        try:
            if "-" in date_str and len(date_str.split("-")[0]) == 4:
                return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
            return date_str
        except Exception:
            return date_str

    def reset_today_cache(
        self, date_str: str, cache_documents: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Initializes or resets documents in 'live_ema_analysis' for the given date.
        Usually executed at 09:10 AM before market opening.

        Args:
            date_str (str): Today's date in 'YYYY-MM-DD' or 'DD-MM-YYYY' format.
            cache_documents (Dict[str, Any]): In-memory market analysis cache dictionary.

        Returns:
            Dict[str, Any]: Reset summary details containing date, total instrument count,
                            and sample metadata for reporting/notifications.
        """
        formatted_date_key = self._convert_date_format(date_str)
        iso_date_str = (
            datetime.strptime(formatted_date_key, "%d-%m-%Y").strftime("%Y-%m-%d")
            if "-" in formatted_date_key and len(formatted_date_key.split("-")[2]) == 4
            else date_str
        )

        logger.info(
            f"Resetting daily EMA structure in database for date: {formatted_date_key}"
        )
        reset_count = 0
        sample_metadata = None

        for key, doc in cache_documents.items():
            instrument_key = doc.get("instrument_key")
            strike = doc.get("strike")
            option_type = doc.get("type")
            symbol = doc.get("trading_symbol")

            if not instrument_key:
                continue

            query = {"instrument_key": instrument_key}
            formatted_ist_time = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

            # Resets current date array under daily while placing status & timestamps at document root
            update = {
                "$set": {
                    "instrument_key": instrument_key,
                    "trading_symbol": symbol,
                    "strike": str(strike) if strike else "",
                    "type": option_type,
                    f"daily.{formatted_date_key}": [],
                    "last_updated_date": iso_date_str,
                    "last_updated": formatted_ist_time,
                    "status": "NO_CROSSOVER",
                    "total_crosses": 0,
                }
            }

            try:
                live_ema_coll.update_one(query, update, upsert=True)
                reset_count += 1

                # Capture sample metadata from the first valid processed instrument
                if not sample_metadata:
                    sample_metadata = {
                        "instrument_key": instrument_key,
                        "trading_symbol": symbol,
                        "strike": str(strike) if strike else "",
                        "type": option_type,
                    }
            except Exception as e:
                logger.error(f"Failed to reset EMA document for key {key}: {e}")

        logger.info(
            f"Successfully initialized {reset_count} documents for {formatted_date_key}."
        )

        # Return reset summary details
        return {
            "date": formatted_date_key,
            "iso_date": iso_date_str,
            "total_instruments": reset_count,
            "sample_instrument": sample_metadata or {},
        }

    def save_instrument_crosses(
        self, date_str: str, instrument_key: str, crosses: List[Dict[str, Any]]
    ) -> None:
        """
        Updates the target instrument document with calculated EMA crossover events.
        Works for both Live updates and Recovery mode.

        Args:
            date_str (str): Date in 'YYYY-MM-DD' or 'DD-MM-YYYY' format.
            instrument_key (str): Upstox instrument key (e.g., 'NSE_FO|63959').
            crosses (List[Dict[str, Any]]): List of calculated crossover dicts.
        """
        try:
            formatted_date_key = self._convert_date_format(date_str)
            iso_date_str = (
                datetime.strptime(formatted_date_key, "%d-%m-%Y").strftime("%Y-%m-%d")
                if "-" in formatted_date_key
                and len(formatted_date_key.split("-")[2]) == 4
                else date_str
            )

            status = "CROSSOVER_FOUND" if len(crosses) > 0 else "NO_CROSSOVER"

            formatted_crosses = [
                {
                    "timestamp": c.get("timestamp"),
                    "signal": c.get("signal"),
                    "short_ema": float(c.get("short_ema", 0.0)),
                    "long_ema": float(c.get("long_ema", 0.0)),
                    "price": float(c.get("price", 0.0)),
                }
                for c in crosses
            ]

            formatted_ist_time = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

            query = {"instrument_key": instrument_key}
            update = {
                "$set": {
                    f"daily.{formatted_date_key}": formatted_crosses,
                    "last_updated_date": iso_date_str,
                    "last_updated": formatted_ist_time,
                    "status": status,
                    "total_crosses": len(formatted_crosses),
                }
            }

            live_ema_coll.update_one(query, update, upsert=True)

        except Exception as e:
            logger.error(
                f"Failed to save EMA crosses for instrument {instrument_key}: {e}"
            )

    def get_instrument_crosses(self, date_str: str, instrument_key: str) -> dict | None:
        """
        Retrieves live EMA cross record for a specific instrument and date from MongoDB.
        """
        try:
            formatted_date_key = self._convert_date_format(date_str)

            doc = live_ema_coll.find_one(
                {
                    "instrument_key": instrument_key,
                    f"daily.{formatted_date_key}": {"$exists": True},
                }
            )
            if doc:
                return {
                    "crosses": doc.get("daily", {}).get(formatted_date_key, []),
                    "status": doc.get("status"),
                    "total_crosses": doc.get("total_crosses"),
                    "last_updated": doc.get("last_updated"),
                    "last_updated_date": doc.get("last_updated_date"),
                }
            return None
        except Exception as e:
            logger.error(
                f"Error fetching instrument crosses for {instrument_key} on {date_str}: {e}"
            )
            return None


# Global instance export
live_ema_service = LiveEMAService()
