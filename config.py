import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SELENIUM_APP_BOT = os.getenv("SELENIUM_APP_BOT")
MONGO_URL = os.getenv("MONGO_URL")

TRADINGVIEW_URL = os.getenv(
    "TRADINGVIEW_URL", "https://in.tradingview.com/chart/b5ZdnUGQ/"
)

PROFILE_PATH = os.getenv("PROFILE_PATH", r"D:\ChromeProfiles\TradingView")
