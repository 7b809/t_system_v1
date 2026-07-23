# core/db.py

from pymongo import MongoClient
from core.config import settings
from core.logger import get_logger

logger = get_logger("db")


class Database:
    """
    Database management class for UPSTOX_APP.
    Handles MongoClient lifecycle and collection access.
    """

    def __init__(self):
        try:
            # Initialize MongoDB Client
            self.client = MongoClient(settings.MONGO_URL)
            self.db = self.client[settings.UPSTOX_DB]

            logger.info(f"Connected to MongoDB database: '{settings.UPSTOX_DB}'")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise e

    # ------------------------------------------------------------------
    # Collection Properties
    # ------------------------------------------------------------------
    @property
    def live_ema_collection(self):
        """Returns the UPSTOX_EMA_COLL collection ('live_ema_analysis')"""
        return self.db[settings.UPSTOX_EMA_COLL]

    @property
    def market_analysis_collection(self):
        """Returns the UPSTOX_STRIKES_COLL collection ('market_analysis')"""
        return self.db[settings.UPSTOX_STRIKES_COLL]

    @property
    def tokens_collection(self):
        """Returns the UPSTOX_TOKEN_COLL collection ('upstox_tokens')"""
        return self.db[settings.UPSTOX_TOKEN_COLL]


# Database Singleton Instance
db_instance = Database()

# Helper exports for direct collection import
live_ema_coll = db_instance.live_ema_collection
market_analysis_coll = db_instance.market_analysis_collection
tokens_coll = db_instance.tokens_collection
