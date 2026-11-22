# ============================================================
# ارسال اخبار به تلگرام و بله با قالب حرفه‌ای و تاریخ شمسی
# ============================================================

import requests
import time
from src.utils import to_shamsi, now_shamsi

def send_to_telegram(token, chat_id, text, max_retries=3):
    """ارسال پیام به کانال تلگرام"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": False
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return True
            print(f"  ⚠️ تلگرام: {data.get('description','خطای نامشخص')}")
            if "retry_after" in str(data):
                time.sleep(35)
        except Exception as e:
            print(f"  ❌ خطا در ارسال به تلگرام (تلاش {attempt+1}): {e}")
            time.sleep(3)
    return False


def send_to_bale(token, chat_id, text, max_retries=3):
    """ارسال پیام به کانال بله"""
    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return True
            print(f"  ⚠️ بله: {data.get('description','خطای نامشخص')}")
        except Exception as e:
            print(f"  ❌ خطا در ارسال به بله (تلاش {attempt+1}): {e}")
            time.sleep(3)
    return False


def format_message(item, channel_username=""):
    """قالب‌بندی حرفه‌ای پیام با تاریخ شمسی"""

    emoji     = item.get("emoji", "🌱")
    cat_fa    = item.get("category_fa", "")
    title     = item.get("title", "")
    summary   = item.get("summary", "")
    source_fa = item.get("source_fa", item.get("source", ""))
    link      = item.get("link", "")
    published = item.get("published", "")

    # تبدیل تاریخ به شمسی
    shamsi_time = to_shamsi(published) if published else now_shamsi("%Y/%m/%d %H:%M")

    # خلاصه‌سازی (حداکثر ۲۸۰ کاراکتر)
    short_summary = summary[:280] + "..." if len(summary) > 280 else summary

    # ساخت پیام
    msg = (
        f"{emoji} <b>{cat_fa}</b>\n"
        f"{'─' * 32}\n\n"
        f"📌 <b>{title}</b>\n\n"
    )

    if short_summary:
        msg += f"📝 <i>{short_summary}</i>\n\n"

    msg += (
        f"{'─' * 32}\n"
        f"🗞 منبع: <b>{source_fa}</b>\n"
        f"📅 تاریخ: <b>{shamsi_time}</b>\n"
        f"🔗 <a href='{link}'>مشاهده خبر کامل</a>\n\n"
        f"🌿 <i>سامانه ملی پایش اخبار محیط زیست ایران</i>"
    )

    if channel_username:
        msg += f"\n📢 {channel_username}"

    return msg
