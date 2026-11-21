# ============================================================
# تنظیمات مرکزی پروژه
# ============================================================

import os

class Config:
    # تلگرام
    TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TG_CHAT_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

    # بله
    BALE_TOKEN   = os.getenv("BALE_BOT_TOKEN", "")
    BALE_CHAT_ID = os.getenv("BALE_CHANNEL_ID", "")

    # کلودفلر
    CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
    CF_API_TOKEN  = os.getenv("CF_API_TOKEN", "")
    D1_DB_ID      = os.getenv("D1_DATABASE_ID", "")

    # تنظیمات عمومی
    CHANNEL_USERNAME = "@YourChannelID"  # آیدی کانال تلگرام خود را اینجا بنویسید
    MAX_NEWS_PER_RUN = 30  # حداکثر اخبار ارسالی در هر اجرا
    DELAY_BETWEEN_SENDS = 3  # ثانیه تأخیر بین ارسال‌ها
