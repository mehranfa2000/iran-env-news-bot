# ============================================================
#  src/config.py — تنظیمات مرکزی پروژه
# ============================================================

import os

# ── توکن‌ها و شناسه‌ها (از GitHub Secrets) ──────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
BALE_BOT_TOKEN      = os.getenv("BALE_BOT_TOKEN",      "")
BALE_CHANNEL_ID     = os.getenv("BALE_CHANNEL_ID",     "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY",       "")

# ── تنظیمات ارسال ────────────────────────────────────────────
MAX_NEWS_PER_RUN    = 30
DELAY_BETWEEN_SENDS = 3
MAX_STORED_NEWS     = 500

# ── تنظیمات فیلتر ────────────────────────────────────────────
SCORE_THRESHOLD_DEDICATED = 2
SCORE_THRESHOLD_GENERAL   = 4
TITLE_SCORE_WEIGHT        = 3
BODY_SCORE_WEIGHT         = 1

# ── تنظیمات AI ────────────────────────────────────────────────
AI_MODEL            = "gemini-3.8-flash"
AI_ENABLED          = bool(GEMINI_API_KEY)
AI_MAX_PER_RUN      = 30
AI_TIMEOUT          = 30

# ── آدرس‌های API ─────────────────────────────────────────────
TELEGRAM_API_BASE = "https://api.telegram.org/bot"
BALE_API_BASE     = "https://tapi.bale.ai/bot"

# ── امضای ربات ───────────────────────────────────────────────
BOT_SIGNATURE = "🌿 سامانه پایش اخبار محیط زیست ایران"
