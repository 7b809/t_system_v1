# core/config.py

import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Settings:
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME = os.getenv("APP_NAME", "UPSTOX_APP")
    APP_VERSION = os.getenv("APP_VERSION", "2.0")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    MONGO_URL = os.getenv("MONGO_URL")

    UPSTOX_DB = os.getenv("UPSTOX_DB", "UPSTOX_APP")
    UPSTOX_TOKEN_COLL = os.getenv("UPSTOX_TOKEN_COLL", "upstox_tokens")
    UPSTOX_STRIKES_COLL = os.getenv("UPSTOX_STRIKES_COLL", "market_analysis")
    UPSTOX_EMA_COLL = os.getenv("UPSTOX_EMA_COLL", "live_ema_analysis")

    # ------------------------------------------------------------------
    # Upstox
    # ------------------------------------------------------------------
    ACCESS_TOKEN_DOCUMENT_ID = os.getenv(
        "ACCESS_TOKEN_DOCUMENT_ID",
        "upstox_access_token",
    )
    UPSTOX_API_VERSION = os.getenv("UPSTOX_API_VERSION", "2.0")
    UPSTOX_FEED_MODE = os.getenv("UPSTOX_FEED_MODE", "ltpc")
    NIFTY_INDEX_INSTRUMENT_KEY = os.getenv(
        "NIFTY_INDEX_INSTRUMENT_KEY",
        "NSE_INDEX|Nifty 50",
    )

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_FLAG = False

    
    # ------------------------------------------------------------------
    # EMA
    # ------------------------------------------------------------------
    EMA_SHORT_PERIOD = int(os.getenv("EMA_SHORT_PERIOD", "9"))
    EMA_LONG_PERIOD = int(os.getenv("EMA_LONG_PERIOD", "21"))

    # ------------------------------------------------------------------
    # Candle
    # ------------------------------------------------------------------
    CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "1minute")

    # ------------------------------------------------------------------
    # Market Timing
    # ------------------------------------------------------------------
    MARKET_START_HOUR = int(os.getenv("MARKET_START_HOUR", "9"))
    MARKET_START_MINUTE = int(os.getenv("MARKET_START_MINUTE", "15"))

    MARKET_END_HOUR = int(os.getenv("MARKET_END_HOUR", "15"))
    MARKET_END_MINUTE = int(os.getenv("MARKET_END_MINUTE", "30"))

    PRELOAD_HOUR = int(os.getenv("PRELOAD_HOUR", "8"))
    PRELOAD_MINUTE = int(os.getenv("PRELOAD_MINUTE", "0"))

    TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    SCHEDULER_SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP_SECONDS", "15"))

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "5"))
    RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))

    SUBSCRIBE_BATCH_SIZE = int(os.getenv("SUBSCRIBE_BATCH_SIZE", "100"))
    SUBSCRIBE_BATCH_SLEEP = float(os.getenv("SUBSCRIBE_BATCH_SLEEP", "0.5"))

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------
    ENABLE_HEALTH_CHECK = os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true"
    HEALTH_CHECK_INTERVAL_SECONDS = int(
        os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "60")
    )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    STATS_INTERVAL_SECONDS = int(os.getenv("STATS_INTERVAL_SECONDS", "300"))

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    STORE_CROSSES = os.getenv("STORE_CROSSES", "true").lower() == "true"

    STORE_MASTER_CANDLES = os.getenv("STORE_MASTER_CANDLES", "true").lower() == "true"

    STORE_TODAY_CANDLES = os.getenv("STORE_TODAY_CANDLES", "true").lower() == "true"


settings = Settings()
