# ============================================================
# ارسال اخبار به تلگرام و بله با قالب حرفه‌ای
# ============================================================

import requests
import time

def send_to_telegram(token, chat_id, text, max_retries=3):
    """ارسال پیام به کانال تلگرام"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return True
            else:
                print(f"  ⚠️ تلگرام خطا داد: {data.get('description')}")
                # اگر rate limit بود، صبر کن
                if "retry_after" in str(data):
                    time.sleep(30)
        except Exception as e:
            print(f"  ❌ خطا در ارسال به تلگرام (تلاش {attempt+1}): {e}")
            time.sleep(3)
    return False

def send_to_bale(token, chat_id, text, max_retries=3):
    """ارسال پیام به کانال بله"""
    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return True
            else:
                print(f"  ⚠️ بله خطا داد: {data.get('description')}")
        except Exception as e:
            print(f"  ❌ خطا در ارسال به بله (تلاش {attempt+1}): {e}")
            time.sleep(3)
    return False

def format_message(item, channel_username=""):
    """قالب‌بندی حرفه‌ای پیام خروجی"""
    
    emoji    = item.get("emoji", "🌱")
    cat_fa   = item.get("category_fa", "")
    title    = item.get("title", "")
    summary  = item.get("summary", "")
    source_fa= item.get("source_fa", item.get("source", ""))
    link     = item.get("link", "")
    published= item.get("published", "")

    # خلاصه‌سازی (حداکثر ۲۵۰ کاراکتر)
    short_summary = summary[:250] + "..." if len(summary) > 250 else summary

    # ساخت پیام
    msg = (
        f"{emoji} <b>{cat_fa}</b>\n"
        f"{'─' * 30}\n\n"
        f"📌 <b>{title}</b>\n\n"
    )
    
    if short_summary:
        msg += f"📝 {short_summary}\n\n"
    
    msg += (
        f"{'─' * 30}\n"
        f"🗞 منبع: <b>{source_fa}</b>\n"
    )
    
    if published:
        msg += f"🕐 زمان انتشار: {published[:16]}\n"
    
    msg += (
        f"🔗 <a href='{link}'>مشاهده خبر کامل</a>\n\n"
        f"🌿 <i>پایش هوشمند اخبار محیط زیست ایران</i>"
    )
    
    if channel_username:
        msg += f"\n📢 {channel_username}"

    return msg
