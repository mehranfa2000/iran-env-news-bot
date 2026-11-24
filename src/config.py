"""
config.py — v4.0
سازمان حفاظت محیط‌زیست ایران | سامانه پایش هوشمند اخبار
تمامی تنظیمات مرکزی پروژه
"""

from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field
from typing import Final

# ═══════════════════════════════════════════════════════════════
# ۱) لاگینگ حرفه‌ای
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("config")

# ═══════════════════════════════════════════════════════════════
# ۲) متغیرهای محیطی (از GitHub Secrets)
# ═══════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN: Final[str] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: Final[str] = os.environ.get("TELEGRAM_CHANNEL_ID", "")
BALE_BOT_TOKEN: Final[str]      = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHANNEL_ID: Final[str]     = os.environ.get("BALE_CHANNEL_ID", "")
GEMINI_API_KEY: Final[str]      = os.environ.get("GEMINI_API_KEY", "")

# ═══════════════════════════════════════════════════════════════
# ۳) آدرس‌های API
# ═══════════════════════════════════════════════════════════════
TELEGRAM_API_BASE: Final[str] = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
BALE_API_BASE: Final[str]     = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}"

# ═══════════════════════════════════════════════════════════════
# ۴) مدل هوش مصنوعی
# ═══════════════════════════════════════════════════════════════
AI_MODEL: Final[str]           = "gemini-2.0-flash"
AI_MAX_PER_RUN: Final[int]     = 5          # حداکثر تحلیل در هر اجرا
AI_MAX_PER_DAY: Final[int]     = 20         # حداکثر تحلیل روزانه
AI_SUMMARY_MAX_PER_RUN: Final[int] = 15     # خلاصه‌سازی AI برای خبرهای عادی
AI_TEMPERATURE: Final[float]   = 0.3        # دقت بالا، خلاقیت کمتر

# ═══════════════════════════════════════════════════════════════
# ۵) تنظیمات ذخیره‌سازی
# ═══════════════════════════════════════════════════════════════
NEWS_FILE: Final[str]           = "data/news.json"
DAILY_ANALYSIS_FILE: Final[str] = "data/daily_analysis.json"
RUN_STATS_FILE: Final[str]      = "data/run_stats.json"
MAX_STORED_NEWS: Final[int]     = 1000      # حداکثر خبر ذخیره‌شده
MAX_NEWS_PER_RUN: Final[int]    = 30        # حداکثر خبر جدید در هر اجرا

# ═══════════════════════════════════════════════════════════════
# ۶) تنظیمات collector
# ═══════════════════════════════════════════════════════════════
COLLECTOR_MAX_WORKERS: Final[int]  = 6      # تعداد thread های موازی
COLLECTOR_TIMEOUT: Final[int]      = 20     # timeout هر درخواست (ثانیه)
COLLECTOR_MAX_RETRIES: Final[int]  = 3      # تعداد تلاش مجدد
FEED_MAX_ENTRIES: Final[int]       = 30     # حداکثر خبر از هر فید

# ═══════════════════════════════════════════════════════════════
# ۷) تنظیمات فیلتر
# ═══════════════════════════════════════════════════════════════
SCORE_THRESHOLD_DEDICATED: Final[int] = 2  # آستانه برای فیدهای اختصاصی
SCORE_THRESHOLD_GENERAL: Final[int]   = 5  # آستانه برای فیدهای عمومی
CRITICAL_SCORE_THRESHOLD: Final[int]  = 15 # آستانه خبر بحرانی

# ═══════════════════════════════════════════════════════════════
# ۸) تنظیمات ارسال
# ═══════════════════════════════════════════════════════════════
DELAY_BETWEEN_SENDS: Final[int]    = 4     # تأخیر بین ارسال‌ها (ثانیه)
DELAY_BETWEEN_PLATFORMS: Final[int]= 2     # تأخیر بین تلگرام و بله
MAX_CAPTION_LENGTH: Final[int]     = 1024  # محدودیت caption تلگرام/بله
MAX_MESSAGE_LENGTH: Final[int]     = 4096  # محدودیت پیام متنی

# ═══════════════════════════════════════════════════════════════
# ۹) تصویر پیش‌فرض اگر خبر تصویر نداشت
# ═══════════════════════════════════════════════════════════════
DEFAULT_IMAGE_URL: Final[str] = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/"
    "Iran_in_its_region.svg/800px-Iran_in_its_region.svg.png"
)
ENV_LOGO_URL: Final[str] = (
    "https://upload.wikimedia.org/wikipedia/fa/thumb/0/0d/"
    "Iran_DOE_logo.svg/200px-Iran_DOE_logo.svg.png"
)

# ═══════════════════════════════════════════════════════════════
# ۱۰) امضای ربات
# ═══════════════════════════════════════════════════════════════
BOT_SIGNATURE: Final[str] = (
    "🌿 <b>سامانه پایش هوشمند اخبار محیط‌زیست</b>\n"
    "🏛 روابط‌عمومی سازمان حفاظت محیط‌زیست ایران"
)

# ═══════════════════════════════════════════════════════════════
# ۱۱) دسته‌بندی‌های محیط‌زیستی
# ═══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Category:
    id: str
    name: str
    emoji: str
    color: str          # برای داشبورد

CATEGORIES: Final[list[Category]] = [
    Category("air_water_soil",  "آلودگی هوا، آب و خاک",          "🌬️", "#ef4444"),
    Category("wildlife",        "حیات وحش و تنوع زیستی",         "🐆", "#f97316"),
    Category("water_wetlands",  "تالاب‌ها، دریاها و منابع آب",    "🌊", "#3b82f6"),
    Category("climate",         "تغییر اقلیم و بحران‌های طبیعی",  "🌡️", "#8b5cf6"),
    Category("forests",         "جنگل‌ها، مراتع و منابع طبیعی",   "🌲", "#22c55e"),
    Category("policy",          "سیاست‌ها، قوانین و سازمان",       "🏛️", "#64748b"),
    Category("sustainable",     "توسعه پایدار و انرژی پاک",       "♻️", "#10b981"),
]

CATEGORY_MAP: Final[dict[str, Category]] = {c.id: c for c in CATEGORIES}

# ═══════════════════════════════════════════════════════════════
# ۱۲) فیدهای RSS (۱۴ فید)
# ═══════════════════════════════════════════════════════════════
@dataclass
class FeedConfig:
    name: str
    url: str
    dedicated: bool = True      # فید اختصاصی محیط‌زیست؟
    skip_on_error: bool = False
    priority: int = 1           # اولویت (۱=بالا)

FEEDS: Final[list[FeedConfig]] = [
    FeedConfig("ایرنا محیط‌زیست",     "https://www.irna.ir/rss/tp/32",                   dedicated=True,  priority=1),
    FeedConfig("مهر محیط‌زیست",       "https://www.mehrnews.com/rss/tp/64",               dedicated=True,  priority=1),
    FeedConfig("ایسنا محیط‌زیست",     "https://www.isna.ir/rss/tp/13",                   dedicated=True,  priority=1),
    FeedConfig("فارس محیط‌زیست",      "https://www.farsnews.ir/rss/tp/13",                dedicated=True,  priority=1),
    FeedConfig("تسنیم",               "https://www.tasnimnews.com/fa/rss/feed/0/8/0",    dedicated=True,  priority=1),
    FeedConfig("ایمنا",               "https://www.imna.ir/rss/tp/153",                  dedicated=True,  priority=2),
    FeedConfig("اطلاعات",             "https://www.ettelaat.com/rss/tp/65",              dedicated=True,  priority=2),
    FeedConfig("صدا و سیما محیط‌زیست","https://www.iribnews.ir/fa/rss/7/39",             dedicated=True,  priority=2),
    FeedConfig("صدا و سیما آب",        "https://www.iribnews.ir/fa/rss/6/8",              dedicated=True,  priority=2),
    FeedConfig("سلامت نیوز",          "https://www.salamatnews.com/rss/tp/11",           dedicated=True,  priority=2),
    FeedConfig("همشهری محیط‌زیست",    "https://www.hamshahrionline.ir/rss/tp/584",       dedicated=True,  priority=2),
    FeedConfig("خبرآنلاین",           "https://www.khabaronline.ir/rss/tp/44",           dedicated=True,  priority=2),
    FeedConfig("ایسنا عمومی",         "https://www.isna.ir/rss",                         dedicated=False, priority=3),
    FeedConfig("باشگاه خبرنگاران",    "https://www.yjc.ir/fa/rss/5/74",                 dedicated=True,  skip_on_error=True, priority=3),
]

# ═══════════════════════════════════════════════════════════════
# ۱۳) اعتبارسنجی
# ═══════════════════════════════════════════════════════════════
def validate_config() -> bool:
    """بررسی می‌کند که همه متغیرهای ضروری تنظیم شده‌اند."""
    missing = []
    for var_name, value in [
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHANNEL_ID", TELEGRAM_CHANNEL_ID),
        ("BALE_BOT_TOKEN", BALE_BOT_TOKEN),
        ("BALE_CHANNEL_ID", BALE_CHANNEL_ID),
        ("GEMINI_API_KEY", GEMINI_API_KEY),
    ]:
        if not value:
            missing.append(var_name)
    if missing:
        logger.error("متغیرهای محیطی یافت نشد: %s", ", ".join(missing))
        return False
    logger.info("✅ تمام متغیرهای محیطی تنظیم شده‌اند.")
    return True
