import os
import urllib.request
import urllib.error
import json
import logging

logger = logging.getLogger(__name__)


class TelegramNotificationService:

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # ----------------------------------------------------
        # Notification Enable Flag
        # ----------------------------------------------------
        self.tele_flag = True
        
        
        # ----------------------------------------------------
        # Credential Validation
        # ----------------------------------------------------
        self.credentials_valid = bool(self.bot_token and self.chat_id)

        if not self.credentials_valid:
            logger.warning("Telegram credentials missing. Notifications are disabled.")

        elif not self.tele_flag:
            logger.info("Telegram notifications are disabled via TELE_FLAG=false.")

        else:
            logger.info("Telegram notification service enabled.")

    def _send_message(self, text: str):
        """
        Send MarkdownV2 formatted Telegram message.
        """

        if not self.credentials_valid:
            return

        if not self.tele_flag:
            logger.debug("Telegram message skipped because TELE_FLAG=false.")
            return

        url = f"https://api.telegram.org/" f"bot{self.bot_token}/sendMessage"

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        }

        try:
            data = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode("utf-8")

                if response.status != 200:
                    logger.error(f"Telegram API returned {response.status}: {body}")

        except urllib.error.HTTPError as ex:
            try:
                error_body = ex.read().decode("utf-8")
            except Exception:
                error_body = ""

            if ex.code == 401:
                logger.error(
                    "Telegram bot token is invalid or expired "
                    f"(HTTP 401). {error_body}"
                )
            else:
                logger.error(
                    f"Telegram HTTP error {ex.code}: " f"{ex.reason} {error_body}"
                )

        except Exception as ex:
            logger.error(f"Failed to send Telegram notification: {ex}")

    def escape_markdown(self, text: str) -> str:
        """
        Escape Telegram MarkdownV2 special characters.

        Telegram MarkdownV2 reserved characters:
        _ * [ ] ( ) ~ ` > # + - = | { } . !
        """

        escape_chars = r'_*~`>#+-=|{}.!'
        return "".join(
            f"\\{char}" if char in escape_chars else char for char in str(text)
        )

    def send_app_started(self, date_str: str):
        """
        Triggered when the application boots successfully.
        """

        msg = (
            "🚀 *System Initialization*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            "🔄 *Status:* Market monitoring engine has booted successfully\\. "
            "Verifying schedule\\.\\.\\."
        )

        self._send_message(msg)

    def send_market_skipped(self, date_str: str, reason: str):
        """
        Triggered if today is a weekend or official trading holiday.
        """

        icon = "⏸️" if "weekend" in reason.lower() else "🌴"

        msg = (
            f"{icon} *Market Session Skipped*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"🚫 *Reason:* {self.escape_markdown(reason)}\n"
            "😴 Engine entering standby until next scheduled day\\."
        )

        self._send_message(msg)

    def send_preload_summary(
        self,
        total_strikes: int,
        duration_secs: float,
    ):
        """
        Triggered after runtime preload completes.
        """

        msg = (
            "⚙️ *Preload Complete*\n\n"
            f"📊 *Instruments Loaded:* `{total_strikes}`\n"
            f"⏳ *Duration:* `{duration_secs:.2f}s`\n"
            "✅ Runtime state initialized successfully\\.\n"
            "🚀 Awaiting market feed startup\\."
        )

        self._send_message(msg)

    def send_intraday_recovery_summary(
        self,
        recovered_instruments: int,
    ):
        """
        Sent when startup intraday recovery completes.
        """

        msg = (
            "♻️ *Intraday Recovery Complete*\n\n"
            f"📊 *Recovered Instruments:* `{recovered_instruments}`\n"
            "✅ Runtime EMA state rebuilt using Mongo snapshots and intraday candles\\.\n"
            "🚀 Live WebSocket startup beginning\\."
        )

        self._send_message(msg)

    def send_market_stopped_summary(
        self,
        date_str: str,
        success_count: int,
        failed_count: int,
    ):
        """
        Triggered during market close cleanup.
        """

        status_icon = "✅" if failed_count == 0 else "⚠️"

        msg = (
            f"{status_icon} *Daily Session Concluded*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"🟩 *Successful Updates:* `{success_count}`\n"
            f"🟥 *Failed Streams/Calculations:* `{failed_count}`\n\n"
            "🔒 All open 1\\-min candles flushed, socket detached, and memory maps purged\\."
        )

        self._send_message(msg)

    def send_upstox_token_expired(
        self,
        date_str: str,
        error_details: str,
    ):
        """
        Triggered when Upstox authentication fails.
        """

        msg = (
            "🔑 *UPSTOX AUTHENTICATION FAILURE*\n\n"
            f"📅 *Date:* {self.escape_markdown(date_str)}\n"
            f"❌ *Error Details:* `{self.escape_markdown(error_details)}`\n\n"
            "⚠️ *Action Required:* Please re\\-authenticate your broker session "
            "to generate a fresh Access Token in MongoDB immediately\\."
        )

        self._send_message(msg)

    def send_critical_alert(
        self,
        stage: str,
        error_msg: str,
    ):
        """
        Urgent alert requiring manual attention.
        """

        msg = (
            "🚨 *CRITICAL SYSTEM ERROR*\n\n"
            f"💥 *Stage:* {self.escape_markdown(stage)}\n"
            f"❌ *Error:* `{self.escape_markdown(error_msg)}`\n\n"
            "⚠️ *Manual intervention required immediately\\.*"
        )

        self._send_message(msg)
