from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.settings import Settings


def now():
    return datetime.now(ZoneInfo(Settings.TIMEZONE))


def utc_now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat()


def now_string():
    return now().strftime("%d %b %Y, %I:%M:%S %p %Z")


def format_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(
        ZoneInfo(Settings.TIMEZONE)
    ).strftime("%d %b %Y, %I:%M:%S %p %Z")