from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from config.settings import Settings
from core.logger import get_logger

logger = get_logger(__name__)


class MongoApp:
    """
    Central MongoDB Connection Manager
    """

    _client = None
    _db = None

    @classmethod
    def connect(cls):
        """
        Initialize MongoDB connection only once.
        """

        try:
            if cls._client is None:
                cls._client = MongoClient(
                    Settings.MONGO_URI, serverSelectionTimeoutMS=5000
                )

                # Verify connection
                cls._client.admin.command("ping")

                cls._db = cls._client[Settings.UPSTOX_DB]

                logger.info(
                    f"MongoDB connected successfully | " f"DB={Settings.UPSTOX_DB}"
                )

            return cls._db

        except Exception as ex:
            logger.exception(f"Failed to connect MongoDB: {ex}")
            raise

    @classmethod
    def get_db(cls) -> Database:
        """
        Returns database instance.
        """

        if cls._db is None:
            cls.connect()

        return cls._db

    @classmethod
    def get_token_collection(cls) -> Collection:
        """
        Returns token collection.
        """

        logger.debug(f"Accessing collection: " f"{Settings.UPSTOX_TOKEN_COLL}")

        return cls.get_db()[Settings.UPSTOX_TOKEN_COLL]

    @classmethod
    def get_strikes_collection(cls) -> Collection:
        """
        Returns strikes collection.
        """

        logger.debug(f"Accessing collection: " f"{Settings.UPSTOX_STRIKES_COLL}")

        return cls.get_db()[Settings.UPSTOX_STRIKES_COLL]

    @classmethod
    def close(cls):
        """
        Close Mongo connection.
        """

        try:

            if cls._client:

                cls._client.close()

                logger.info("MongoDB connection closed successfully")

                cls._client = None
                cls._db = None

        except Exception as ex:

            logger.exception(f"Error while closing Mongo connection: {ex}")

    @classmethod
    def get_live_ema_collection(cls):
        """
        Returns live EMA collection.
        """
        return cls.get_db()[Settings.UPSTOX_EMA_COLL]
