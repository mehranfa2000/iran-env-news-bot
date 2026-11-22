# ============================================================
#  src/config.py — تنظیمات مرکزی پروژه
# ============================================================

import os

# ── توکن‌ها و شناسه‌ها (از GitHub Secrets) ──────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
BALE_BOT_TOKEN      = os.getenv("BALE_BOT_TOKEN",      "")
BALE_CHANNEL_ID     = os.getenv("BALE_CHANNEL_ID",     "")

# ── تنظیمات ارسال ────────────────────────────────────────────
MAX_NEWS_PER_RUN    = 30     # حداکثر خبر در هر اجرا
DELAY_BETWEEN_SENDS = 3      # ثانیه تأخیر بین ارسال‌ها
MAX_STORED_NEWS     = 500    # حداکثر اخبار در news.json

# ── تنظیمات فیلتر ────────────────────────────────────────────
SCORE_THRESHOLD_DEDICATED = 2   # امتیاز کمینه برای فیدهای اختصاصی
SCORE_THRESHOLD_GENERAL   = 4   # امتیاز کمینه برای فیدهای عمومی
TITLE_SCORE_WEIGHT        = 3   # وزن کلیدواژه در عنوان
BODY_SCORE_WEIGHT         = 1   # وزن کلیدواژه در متن

# ── آدرس‌های API ─────────────────────────────────────────────
TELEGRAM_API_BASE = "https://api.telegram.org/bot"
BALE_API_BASE     = "https://tapi.bale.ai/bot"

# ── امضای ربات ───────────────────────────────────────────────
BOT_SIGNATURE = "🌿 سامانه پایش اخبار محیط زیست ایران\n@iran_env_news"
