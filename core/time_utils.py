# core/time_utils.py

from datetime import datetime
import pytz
from core.config import settings

def get_ist_now() -> datetime:
    """Returns current datetime in Indian Standard Time (Asia/Kolkata)."""
    tz = pytz.timezone(settings.TIMEZONE)
    return datetime.now(tz)

def get_ist_formatted(fmt: str = "%Y-%m-%d %I:%M:%S %p IST") -> str:
    """
    Returns formatted 12-hour readable IST time string.
    Example output: '2026-07-23 09:32:24 PM IST'
    """
    return get_ist_now().strftime(fmt)

def get_ist_date_str() -> str:
    """Returns today's date in YYYY-MM-DD format based on IST."""
    return get_ist_now().strftime("%Y-%m-%d")