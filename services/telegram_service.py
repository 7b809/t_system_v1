import os
import urllib.request
import urllib.parse
import urllib.error  # 1. Added explicit import for handling network-specific exceptions
import json
import logging

logger = logging.getLogger(__name__)


class TelegramNotificationService:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning("Telegram credentials missing. Notifications are disabled.")

    def _send_message(self, text: str):
        """Helper method to send Markdown-formatted messages to Telegram."""
        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "MarkdownV2"}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Telegram API returned status code {response.status}")

        # 2. Intercept explicit HTTP errors to catch code 401 cleanly and avoid verbose tracebacks
        except urllib.error.HTTPError as he:
            if he.code == 401:
                logger.error(
                    "❌ TELEGRAM BOT TOKEN IS EXPIRED OR INVALID (HTTP 401). Please check your .env settings."
                )
            else:
                logger.error(
                    f"Telegram API rejected request (Status {he.code}): {he.reason}"
                )

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    def escape_markdown(self, text: str) -> str:
        """Escapes Telegram MarkdownV2 special characters to prevent parsing errors."""
        escape_chars = r"_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{c}" if c in escape_chars else c for c in str(text))

    def send_app_started(self, date_str: str):
        """Triggered when the daily scheduler boots up successfully."""
        msg = (
            "🚀 *System Initialization*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            "🔄 *Status:* Market monitoring engine has booted successfully\\. Verifying schedule\\.\\.\\."
        )
        self._send_message(msg)

    def send_market_skipped(self, date_str: str, reason: str):
        """Triggered if today is a weekend or an official NSE trading holiday."""
        icon = "⏸️" if "weekend" in reason.lower() else "🌴"
        msg = (
            f"{icon} *Market Session Skipped*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"🚫 *Reason:* {self.escape_markdown(reason)}\n"
            "😴 Engine entering standby until next scheduled day\\."
        )
        self._send_message(msg)

    def send_preload_summary(self, total_strikes: int, duration_secs: float):
        """Triggered after historical cross states are pulled and StrikeState memory map is ready."""
        msg = (
            "⚙️ *Preload & Warmup Complete*\n\n"
            f"📊 *Strikes Tracked:* `{total_strikes}`\n"
            f"⏳ *Time Taken:* `{duration_secs:.2f}s`\n"
            "🟢 WebSocket stream setup initiated\\. Waiting for 09:15 AM\\."
        )
        self._send_message(msg)

    def send_market_stopped_summary(
        self, date_str: str, success_count: int, failed_count: int
    ):
        """Triggered during the 3:30 PM cleanup sequence summarizing the day's processing stats."""
        status_icon = "✅" if failed_count == 0 else "⚠️"
        msg = (
            f"{status_icon} *Daily Session Concluded*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"🟩 *Successful Updates:* `{success_count}`\n"
            f"🟥 *Failed Streams/Calculations:* `{failed_count}`\n\n"
            "🔒 All open 1\\-min candles flushed, socket detached, and memory maps purged\\."
        )
        self._send_message(msg)

    # 3. New specific layout method added for expired or invalid broker session keys
    def send_upstox_token_expired(self, date_str: str, error_details: str):
        """Triggered when the Upstox API rejects authentication (Access Token Expired/Invalid)."""
        msg = (
            "🔑 *UPSTOX AUTHENTICATION FAILURE*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"❌ *Error Details:* `{self.escape_markdown(error_details)}`\n\n"
            "⚠️ *Action Required:* Please re-authenticate your broker session to generate a fresh Access Token in MongoDB immediately\\."
        )
        self._send_message(msg)

    def send_critical_alert(self, stage: str, error_msg: str):
        """Urgent alert requiring manual attention (e.g., token expired, socket crash)."""
        msg = (
            "🚨 *CRITICAL SYSTEM ERROR*\n\n"
            f"💥 *Stage:* {self.escape_markdown(stage)}\n"
            f"❌ *Error:* `{self.escape_markdown(error_msg)}`\n\n"
            "⚠️ *Manual intervention required immediately\\.*"
        )
        self._send_message(msg)
