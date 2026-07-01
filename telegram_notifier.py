import requests
from config import TELEGRAM_CHAT_ID, SELENIUM_APP_BOT


def send_telegram_notification(message: str):
    """
    Sends a synchronous text dispatch notification to your designated Telegram channel/chat.
    """
    if not SELENIUM_APP_BOT or not TELEGRAM_CHAT_ID:
        print("[Telegram Linker] Aborted: Missing Bot Token or Chat ID credentials.")
        return False

    url = f"https://api.telegram.org/bot{SELENIUM_APP_BOT}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return True
        else:
            print(
                f"[Telegram Linker] Error code {response.status_code}: {response.text}"
            )
            return False
    except Exception as e:
        print(f"[Telegram Linker] Network Exception encountered: {str(e)}")
        return False
