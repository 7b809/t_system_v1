# services/telegram_service.py

import asyncio
import httpx
from core.config import settings
from core.logger import get_logger
from core.time_utils import get_ist_formatted

logger = get_logger("telegram_service")


class TelegramService:
    """
    Asynchronous Telegram notification service to alert actions, execution updates,
    and system errors directly to a Telegram Chat/Group.
    """

    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def is_enabled(self) -> bool:
        """Helper check to verify if Telegram notifications are enabled globally."""
        # Fallback check for TELEGRAM_FLAG or TELE_FLAG in settings
        flag = settings.TELEGRAM_FLAG
        return bool(flag)

    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Sends an asynchronous message to the configured Telegram chat if enabled."""
        if not self.is_enabled:
            logger.debug(
                "Telegram notifications are disabled (tele_flag=False). Skipping message."
            )
            return False

        if not self.bot_token or not self.chat_id:
            logger.warning(
                "Telegram credentials missing in environment/config. Message skipped."
            )
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)

                if response.status_code == 200:
                    logger.debug("Telegram alert sent successfully.")
                    return True
                else:
                    logger.error(
                        f"Failed to send Telegram message: {response.status_code} - {response.text}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Error sending message to Telegram: {e}")
            return False

    def send_message_sync(self, message: str) -> None:
        """Helper method to dispatch Telegram notification from synchronous functions."""
        if not self.is_enabled:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.send_message(message))
        except RuntimeError:
            asyncio.run(self.send_message(message))

    # ------------------------------------------------------------------
    # Pre-formatted Application Event Alerts
    # ------------------------------------------------------------------

    async def notify_app_startup(self) -> None:
        """Sends project startup notification."""
        if not self.is_enabled:
            return

        msg = (
            f"🚀 <b>{settings.APP_NAME} Started</b>\n"
            f"<b>Version:</b> {settings.APP_VERSION}\n"
            f"<b>Time:</b> {get_ist_formatted()}\n"
            f"<b>Status:</b> All systems operational."
        )
        await self.send_message(msg)

    async def notify_app_shutdown(self) -> None:
        """Sends project shutdown notification."""
        if not self.is_enabled:
            return

        msg = (
            f"🛑 <b>{settings.APP_NAME} Stopped</b>\n"
            f"<b>Time:</b> {get_ist_formatted()}\n"
            f"<b>Status:</b> Lifespan terminated."
        )
        await self.send_message(msg)

    async def notify_cache_loaded(self, count: int, date_str: str) -> None:
        """Sends daily cache load notification with date and item count."""
        if not self.is_enabled:
            return

        msg = (
            f"📦 <b>Daily Market Analysis Cache Loaded</b>\n"
            f"<b>Date:</b> {date_str}\n"
            f"<b>Total Cached Items:</b> {count}\n"
            f"<b>Time:</b> {get_ist_formatted()}"
        )
        await self.send_message(msg)

    async def notify_market_close(self) -> None:
        """Sends market close alert at 3:30 PM."""
        if not self.is_enabled:
            return

        msg = (
            f"🔔 <b>Market Closed (03:30 PM)</b>\n"
            f"<b>Time:</b> {get_ist_formatted()}\n"
            f"Live calculation loop paused. Entering idle state until next trading day."
        )
        await self.send_message(msg)

    async def notify_pre_market_reset(self) -> None:
        """Sends pre-market reset action status."""
        if not self.is_enabled:
            return

        msg = (
            f"🌅 <b>Pre-Market Daily Reset Completed</b>\n"
            f"<b>Time:</b> {get_ist_formatted()}\n"
            f"Cache refreshed & MongoDB reset for today's market session."
        )
        await self.send_message(msg)

    async def notify_ema_cross_found(
        self, instrument_key: str, cross_type: str, price: float
    ) -> None:
        """Alerts when a new EMA 9/21 cross action occurs."""
        if not self.is_enabled:
            return

        emoji = "📈" if cross_type.upper() == "BULLISH" else "📉"
        msg = (
            f"{emoji} <b>EMA Cross Triggered!</b>\n"
            f"<b>Instrument:</b> <code>{instrument_key}</code>\n"
            f"<b>Signal:</b> {cross_type.upper()}\n"
            f"<b>Price:</b> {price}\n"
            f"<b>Time:</b> {get_ist_formatted()}"
        )
        await self.send_message(msg)

    async def notify_error(self, context: str, error_msg: str) -> None:
        """Sends an exception/error alert."""
        if not self.is_enabled:
            return

        msg = (
            f"⚠️ <b>System Error Alert</b>\n"
            f"<b>Module:</b> {context}\n"
            f"<b>Time:</b> {get_ist_formatted()}\n"
            f"<b>Error:</b> <code>{error_msg}</code>"
        )
        await self.send_message(msg)


# Singleton Export
telegram_service = TelegramService()
