# src/config.py
"""
تنظیمات مرکزی سیستم پایش هوشمند اخبار محیط‌زیست
نسخه ۴.۰ — سازمان حفاظت محیط‌زیست ایران
"""

from __future__ import annotations
import os
import logging

# ─────────────────────────── لاگ‌گیری ───────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("config")

# ─────────────────────────── توکن‌ها و کلیدها ───────────────────────────
TELEGRAM_BOT_TOKEN: str   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str  = os.environ.get("TELEGRAM_CHANNEL_ID", "")
BALE_BOT_TOKEN: str       = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHANNEL_ID: str      = os.environ.get("BALE_CHANNEL_ID", "")
GEMINI_API_KEY: str       = os.environ.get("GEMINI_API_KEY", "")

# ─────────────────────────── مدل هوش مصنوعی ───────────────────────────
AI_MODEL: str             = "gemini-2.0-flash"          # ← مدل فعال
AI_MAX_PER_RUN: int       = 5                            # حداکثر تحلیل کامل در هر اجرا
AI_SUMMARY_MAX_PER_RUN: int = 5                          # حداکثر خلاصه‌سازی در هر اجرا
AI_MAX_PER_DAY: int       = 20                           # حداکثر کل AI در روز
AI_TIMEOUT: int           = 30                           # ثانیه

# ─────────────────────────── مسیرها ───────────────────────────
DATA_DIR: str             = "data"
NEWS_FILE: str            = f"{DATA_DIR}/news.json"
ANALYSIS_FILE: str        = f"{DATA_DIR}/daily_analysis.json"
RUN_STATS_FILE: str       = f"{DATA_DIR}/run_stats.json"

# ─────────────────────────── محدودیت‌های ذخیره‌سازی ───────────────────────────
MAX_STORED_NEWS: int      = 1000
MAX_RUN_STATS: int        = 48                          # آخرین ۴۸ اجرا

# ─────────────────────────── فیلترینگ ───────────────────────────
SCORE_THRESHOLD_DEDICATED: int = 2                      # فیدهای تخصصی محیط‌زیست
SCORE_THRESHOLD_GENERAL: int   = 5                      # فیدهای عمومی
CRITICAL_SCORE_THRESHOLD: int  = 15                     # آستانه خبر بحرانی

# ─────────────────────────── ارسال ───────────────────────────
MAX_NEWS_PER_RUN: int         = 30                      # حداکثر خبر در هر اجرا
DELAY_BETWEEN_SENDS: float    = 4.0                     # ثانیه بین ارسال‌ها
TELEGRAM_CAPTION_MAX: int     = 1024
BALE_CAPTION_MAX: int         = 1024

# ─────────────────────────── کالکتور ───────────────────────────
COLLECTOR_MAX_WORKERS: int    = 6
COLLECTOR_TIMEOUT: int        = 15
COLLECTOR_MAX_RETRIES: int    = 2

# ─────────────────────────── آدرس API ───────────────────────────
TELEGRAM_API_BASE: str = "https://api.telegram.org/bot"
BALE_API_BASE: str     = "https://tapi.bale.ai/bot"

# ─────────────────────────── امضای پیام ───────────────────────────
BOT_SIGNATURE: str = (
    "\n\n🌿 <b>سامانه پایش هوشمند اخبار محیط‌زیست</b>\n"
    "🏛 روابط‌عمومی سازمان حفاظت محیط‌زیست ایران"
)

# ─────────────────────────── دسته‌بندی‌ها ───────────────────────────
CATEGORIES: dict[str, dict] = {
    "air_water_soil": {
        "label": "آلودگی هوا، آب و خاک",
        "emoji": "🌬️",
        "color": "#ef4444",
    },
    "wildlife": {
        "label": "حیات وحش و تنوع زیستی",
        "emoji": "🐆",
        "color": "#f97316",
    },
    "water_wetlands": {
        "label": "تالاب‌ها، دریاها و منابع آب",
        "emoji": "🌊",
        "color": "#3b82f6",
    },
    "climate": {
        "label": "تغییر اقلیم و بحران‌های طبیعی",
        "emoji": "🌡️",
        "color": "#8b5cf6",
    },
    "forests": {
        "label": "جنگل‌ها، مراتع و منابع طبیعی",
        "emoji": "🌲",
        "color": "#22c55e",
    },
    "policy": {
        "label": "سیاست‌ها، قوانین و سازمان",
        "emoji": "🏛️",
        "color": "#64748b",
    },
    "sustainable": {
        "label": "توسعه پایدار و انرژی پاک",
        "emoji": "♻️",
        "color": "#10b981",
    },
}

# ─────────────────────────── فیدهای RSS ───────────────────────────
RSS_FEEDS: list[dict] = [
    # ── فیدهای تخصصی محیط‌زیست (dedicated=True → آستانه پایین‌تر) ──
    {
        "name": "ایرنا محیط‌زیست",
        "url": "https://www.irna.ir/rss/environment.xml",
        "dedicated": True,
        "skip_on_error": False,
    },
    {
        "name": "مهر محیط‌زیست",
        "url": "https://www.mehrnews.com/rss/environment",
        "dedicated": True,
        "skip_on_error": False,
    },
    {
        "name": "صدا و سیما محیط‌زیست",
        "url": "https://www.iribnews.ir/rss/environment",
        "dedicated": True,
        "skip_on_error": False,
    },
    {
        "name": "صدا و سیما آب و خاک",
        "url": "https://www.iribnews.ir/rss/water-soil",
        "dedicated": True,
        "skip_on_error": False,
    },
    {
        "name": "فارس محیط‌زیست",
        "url": "https://www.farsnews.ir/rss/environment",
        "dedicated": True,
        "skip_on_error": True,   # SSL hostname mismatch — harmless
    },
    {
        "name": "ایسنا محیط‌زیست",
        "url": "https://www.isna.ir/rss/tp-78",
        "dedicated": True,
        "skip_on_error": True,   # اغلب fail — harmless
    },
    # ── فیدهای عمومی (dedicated=False → آستانه بالاتر) ──
    {
        "name": "ایرنا عمومی",
        "url": "https://www.irna.ir/rss/latest.xml",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "مهر عمومی",
        "url": "https://www.mehrnews.com/rss/allnews",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "ایمنا",
        "url": "https://www.imna.ir/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "اطلاعات",
        "url": "https://www.ettelaat.com/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "سلامت نیوز",
        "url": "https://www.salamatnews.com/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
    # ── فیدهای پشتیبان ──
    {
        "name": "همشهری",
        "url": "https://www.hamshahrionline.ir/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "خبرآنلاین",
        "url": "https://www.khabaronline.ir/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
    {
        "name": "ایسنا عمومی",
        "url": "https://www.isna.ir/rss",
        "dedicated": False,
        "skip_on_error": False,
    },
]

# ─────────────────────────── user-agent ها ───────────────────────────
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "feedparser/6.0.11 +https://github.com/kurtmckee/feedparser",
    "python-requests/2.32.3",
]

logger.info("✅ تنظیمات بارگذاری شد — مدل: %s", AI_MODEL)
