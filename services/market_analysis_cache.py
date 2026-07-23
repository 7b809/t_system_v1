# services/market_analysis_cache.py

from pymongo import MongoClient

from core.config import settings
from core.logger import get_logger
from core.time_utils import get_ist_date_str
from services.telegram_service import telegram_service

logger = get_logger("market_analysis_cache")


class MarketAnalysisCache:
    """
    Loads the entire market_analysis collection into memory.

    Cache format:

    CACHE = {
        "24500_CE": {...mongo document...},
        "24500_PE": {...mongo document...},
        ...
    }
    """

    def __init__(self):
        self.client = MongoClient(settings.MONGO_URL)
        self.db = self.client["UPSTOX_APP_TEST"]
        self.collection = self.db["market_analysis"]

        self.cache = {}

    def load(self):
        """Load all documents from MongoDB into memory and dispatch Telegram notification."""

        logger.info("Loading market_analysis collection...")

        self.cache.clear()
        total = 0

        try:
            cursor = self.collection.find({})

            for doc in cursor:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                strike = doc.get("strike")
                option_type = doc.get("type")

                if not strike or not option_type:
                    continue

                key = f"{strike}_{option_type}"

                self.cache[key] = doc
                total += 1

            date_str = get_ist_date_str()
            logger.info(f"Loaded {total} documents into cache for date: {date_str}.")

            # 🔔 Telegram Notification for Cache Load / Reload
            telegram_service.send_message_sync(
                f"📦 <b>Market Analysis Cache Loaded</b>\n"
                f"<b>Date:</b> {date_str}\n"
                f"<b>Total Documents Cached:</b> {total}"
            )

        except Exception as e:
            logger.error(f"Error loading market analysis cache: {e}")
            # 🔔 Telegram Exception Alert
            telegram_service.send_message_sync(
                f"⚠️ <b>Cache Load Error Alert</b>\n"
                f"<b>Module:</b> market_analysis_cache\n"
                f"<b>Error:</b> <code>{e}</code>"
            )

    def reload(self):
        logger.info("Reloading market analysis cache...")
        self.load()

    def get(self, strike: str, option_type: str):
        key = f"{strike}_{option_type}"
        return self.cache.get(key)

    def get_by_key(self, key: str):
        return self.cache.get(key)

    def get_all(self):
        return self.cache

    def count(self):
        return len(self.cache)


market_analysis_cache = MarketAnalysisCache()
