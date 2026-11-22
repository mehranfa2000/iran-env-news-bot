# ============================================================
#  src/sender.py — ارسال به تلگرام و بله
#  با تاریخ شمسی و قالب حرفه‌ای
# ============================================================

import requests
from src.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID,
    BALE_BOT_TOKEN,     BALE_CHANNEL_ID,
    TELEGRAM_API_BASE,  BALE_API_BASE,
    BOT_SIGNATURE,
)
from src.utils import parse_rss_date


def _build_message(article: dict) -> str:
    """ساخت متن پیام با قالب استاندارد"""
    emoji    = article.get("category_emoji", "🌿")
    category = article.get("category",       "محیط زیست")
    title    = article.get("title",          "")
    summary  = article.get("summary",        "")
    source   = article.get("source",         "")
    pub_date = parse_rss_date(article.get("published", ""))
    link     = article.get("link",           "")

    # خلاصه را کوتاه می‌کنیم
    if len(summary) > 200:
        summary = summary[:200] + "..."

    msg = (
        f"{emoji} #{category.replace(' ', '_').replace('،', '')}\n\n"
        f"📌 {title}\n\n"
        f"📝 {summary}\n\n"
        f"📰 منبع: {source}\n"
        f"📅 {pub_date}\n\n"
        f"🔗 {link}\n\n"
        f"─────────────────\n"
        f"{BOT_SIGNATURE}"
    )
    return msg


def _send(api_base: str, token: str, chat_id: str, text: str) -> bool:
    """ارسال پیام به یک API (تلگرام یا بله)"""
    if not token or not chat_id:
        return False
    try:
        url  = f"{api_base}{token}/sendMessage"
        data = {
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        r = requests.post(url, json=data, timeout=15)
        result = r.json()
        if result.get("ok"):
            return True
        else:
            # اگر parse_mode مشکل داشت، بدون فرمت امتحان کن
            data["parse_mode"] = ""
            r2 = requests.post(url, json=data, timeout=15)
            return r2.json().get("ok", False)
    except Exception as e:
        print(f"      خطای ارسال: {e}")
        return False


def send_to_telegram(article: dict) -> bool:
    """ارسال یک خبر به کانال تلگرام"""
    msg = _build_message(article)
    return _send(TELEGRAM_API_BASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, msg)


def send_to_bale(article: dict) -> bool:
    """ارسال یک خبر به کانال بله"""
    msg = _build_message(article)
    return _send(BALE_API_BASE, BALE_BOT_TOKEN, BALE_CHANNEL_ID, msg)
