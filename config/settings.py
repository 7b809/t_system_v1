import os

from dotenv import load_dotenv
from datetime import time

load_dotenv()


class Settings:
    """
    Application Settings
    """

    API_VERSION = os.getenv("UPSTOX_API_VERSION", "2.0")
    UPSTOX_EMA_COLL = os.getenv("UPSTOX_EMA_COLL", "live_ema_analysis")
    # =====================================================
    # MONGODB
    # =====================================================

    MONGO_URI = os.getenv("MONGO_URL")

    UPSTOX_DB = os.getenv("UPSTOX_DB", "upstox")

    UPSTOX_TOKEN_COLL = os.getenv("UPSTOX_TOKEN_COLL", "tokens")

    UPSTOX_STRIKES_COLL = os.getenv("UPSTOX_STRIKES_COLL", "option_strikes")

    # =====================================================
    # EMA SETTINGS
    # =====================================================

    EMA_SHORT_PERIOD = int(os.getenv("EMA_SHORT_PERIOD", 9))

    EMA_LONG_PERIOD = int(os.getenv("EMA_LONG_PERIOD", 21))

    # =====================================================
    # MARKET SCHEDULER
    # =====================================================

    PRELOAD_HOUR = int(os.getenv("PRELOAD_HOUR", 9))

    PRELOAD_MINUTE = int(os.getenv("PRELOAD_MINUTE", 0))

    MARKET_START_HOUR = int(os.getenv("MARKET_START_HOUR", 9))

    MARKET_START_MINUTE = int(os.getenv("MARKET_START_MINUTE", 15))

    MARKET_END_HOUR = int(os.getenv("MARKET_END_HOUR", 15))

    MARKET_END_MINUTE = int(os.getenv("MARKET_END_MINUTE", 30))

    PRELOAD_TIME = time(PRELOAD_HOUR, PRELOAD_MINUTE)

    MARKET_START_TIME = time(MARKET_START_HOUR, MARKET_START_MINUTE)

    MARKET_END_TIME = time(MARKET_END_HOUR, MARKET_END_MINUTE)

    # =====================================================
    # CANDLE SETTINGS
    # =====================================================

    CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "1minute")

    TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")

    # =====================================================
    # WEBSOCKET SETTINGS
    # =====================================================

    # UPSTOX_FEED_MODE = os.getenv("UPSTOX_FEED_MODE", "full")
    UPSTOX_FEED_MODE = os.getenv("UPSTOX_FEED_MODE", "ltpc")

    RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", 5))

    MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", 999999))

    # =====================================================
    # SUBSCRIPTION SETTINGS
    # =====================================================

    SUBSCRIBE_BATCH_SIZE = int(os.getenv("SUBSCRIBE_BATCH_SIZE", 100))

    SUBSCRIBE_BATCH_SLEEP = float(os.getenv("SUBSCRIBE_BATCH_SLEEP", 0.5))

    # =====================================================
    # SCHEDULER SETTINGS
    # =====================================================

    SCHEDULER_SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP_SECONDS", 15))

    STATS_INTERVAL_SECONDS = int(os.getenv("STATS_INTERVAL_SECONDS", 300))

    # =====================================================
    # DATA STORAGE SETTINGS
    # =====================================================

    STORE_CROSSES = os.getenv("STORE_CROSSES", "true").lower() == "true"

    STORE_TODAY_CANDLES = os.getenv("STORE_TODAY_CANDLES", "true").lower() == "true"

    STORE_MASTER_CANDLES = os.getenv("STORE_MASTER_CANDLES", "true").lower() == "true"

    # =====================================================
    # LOGGING
    # =====================================================

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", 30))

    # =====================================================
    # APPLICATION
    # =====================================================

    APP_NAME = os.getenv("APP_NAME", "UPSTOX_EMA_CROSSOVER_ENGINE")

    APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

    # =====================================================
    # TIMEZONE
    # =====================================================

    TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

    # =====================================================
    # TOKEN SETTINGS
    # =====================================================

    ACCESS_TOKEN_DOCUMENT_ID = os.getenv(
        "ACCESS_TOKEN_DOCUMENT_ID", "upstox_access_token"
    )

    # =====================================================
    # HEALTH CHECK
    # =====================================================

    ENABLE_HEALTH_CHECK = os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true"

    HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", 60))
