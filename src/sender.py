"""
ارسال‌کننده پیام به تلگرام و بله
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ارسال با Markdown
- retry خودکار (3 بار)
- مدیریت rate limit
"""

import logging
import time
import requests

from src.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    BALE_BOT_TOKEN,
    BALE_CHANNEL_ID,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
BALE_API_BASE     = "https://tapi.bale.ai/bot"

MAX_RETRIES   = 3
RETRY_DELAY   = 5   # ثانیه بین هر تلاش
MAX_MSG_LEN   = 4096


def _send(api_base: str, token: str, chat_id: str, text: str) -> bool:
    """ارسال پیام با retry خودکار"""
    if not token or not chat_id:
        logger.warning("[send] توکن یا chat_id خالی است")
        return False

    # برش متن در صورت طولانی بودن
    if len(text) > MAX_MSG_LEN:
        text = text[:MAX_MSG_LEN - 10] + "\n..."

    url     = f"{api_base}{token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=15)

            if resp.status_code == 200:
                return True

            # rate limit
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
                logger.warning(f"[send] rate limit — صبر {retry_after}s")
                time.sleep(retry_after)
                continue

            # خطای دیگر
            logger.warning(
                f"[send attempt {attempt}] status={resp.status_code} "
                f"body={resp.text[:100]}"
            )

        except requests.RequestException as e:
            logger.warning(f"[send attempt {attempt}] خطای شبکه: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    return False


def send_to_telegram(text: str) -> bool:
    ok = _send(TELEGRAM_API_BASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, text)
    if ok:
        logger.info("[telegram ✅] ارسال موفق")
    else:
        logger.error("[telegram ❌] ارسال ناموفق")
    return ok


def send_to_bale(text: str) -> bool:
    ok = _send(BALE_API_BASE, BALE_BOT_TOKEN, BALE_CHANNEL_ID, text)
    if ok:
        logger.info("[bale ✅] ارسال موفق")
    else:
        logger.error("[bale ❌] ارسال ناموفق")
    return ok
