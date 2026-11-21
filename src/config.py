import os

class Config:
    TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TG_CHAT_ID = os.getenv("TELEGRAM_CHANNEL_ID")
    BALE_TOKEN = os.getenv("BALE_BOT_TOKEN")
    BALE_CHAT_ID = os.getenv("BALE_CHANNEL_ID")
    # تنظیمات دیتابیس در مراحل بعد اضافه می‌شود
