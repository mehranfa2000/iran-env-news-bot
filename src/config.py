"""
config.py — تنظیمات مرکزی سامانه پایش هوشمند محیط‌زیست
نسخه: 4.2.0

اصول:
- هر مقدار قابل override از متغیر محیطی است
- اعتبارسنجی هنگام import (نه runtime)
- هیچ secret داخل کد نیست
- یک منبع واحد برای تمام تنظیمات
"""
from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# توابع کمکی خواندن متغیرهای محیطی
# ══════════════════════════════════════════════════════════════════════════════

def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "")
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return default

def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "")
    try:
        return float(raw.strip())
    except (ValueError, AttributeError):
        return default

def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


# ══════════════════════════════════════════════════════════════════════════════
# مسیرها
# ══════════════════════════════════════════════════════════════════════════════
ROOT             = Path(__file__).parent.parent   # ریشه پروژه
DATA_DIR         = ROOT / "data"
NEWS_JSON_PATH   = str(DATA_DIR / "news.json")
STATS_JSON_PATH  = str(DATA_DIR / "run_stats.json")
DAILY_JSON_PATH  = str(DATA_DIR / "daily_analysis.json")
LOG_PATH         = str(DATA_DIR / "agent.log")


# ══════════════════════════════════════════════════════════════════════════════
# کلیدها و توکن‌ها (فقط از متغیر محیطی)
# ══════════════════════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN:  str = _env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID: str = _env_str("TELEGRAM_CHANNEL_ID")
BALE_BOT_TOKEN:      str = _env_str("BALE_BOT_TOKEN")
BALE_CHANNEL_ID:     str = _env_str("BALE_CHANNEL_ID")
GEMINI_API_KEY:      str = _env_str("GEMINI_API_KEY")


# ══════════════════════════════════════════════════════════════════════════════
# تنظیمات AI
# ══════════════════════════════════════════════════════════════════════════════
AI_MODEL:               str   = _env_str("AI_MODEL", "gemini-3.6-flash")
AI_MAX_PER_RUN:         int   = _env_int("AI_MAX_PER_RUN",    5)
AI_SUMMARY_MAX_PER_RUN: int   = _env_int("AI_SUMMARY_MAX",    5)
AI_MAX_PER_DAY:         int   = _env_int("AI_MAX_PER_DAY",   20)
AI_TIMEOUT_SEC:         int   = _env_int("AI_TIMEOUT_SEC",   30)
AI_RPM_SLEEP:           float = _env_float("AI_RPM_SLEEP",   6.5)   # 10 RPM → حداقل 6s


# ══════════════════════════════════════════════════════════════════════════════
# آدرس‌های API
# ══════════════════════════════════════════════════════════════════════════════
TELEGRAM_API_BASE: str = "https://api.telegram.org/bot"
BALE_API_BASE:     str = "https://tapi.bale.ai/bot"


# ══════════════════════════════════════════════════════════════════════════════
# تنظیمات جمع‌آوری
# ══════════════════════════════════════════════════════════════════════════════
COLLECTOR_MAX_WORKERS:  int   = _env_int("COLLECTOR_MAX_WORKERS", 6)
COLLECTOR_TIMEOUT_SEC:  int   = _env_int("COLLECTOR_TIMEOUT_SEC", 15)
COLLECTOR_RETRY_COUNT:  int   = _env_int("COLLECTOR_RETRY_COUNT",  3)
COLLECTOR_RETRY_DELAY:  float = _env_float("COLLECTOR_RETRY_DELAY", 2.0)


# ══════════════════════════════════════════════════════════════════════════════
# تنظیمات فیلتر
# ══════════════════════════════════════════════════════════════════════════════
SCORE_THRESHOLD_DEDICATED: int = _env_int("SCORE_THRESHOLD_DEDICATED", 2)
SCORE_THRESHOLD_GENERAL:   int = _env_int("SCORE_THRESHOLD_GENERAL",   5)
CRITICAL_SCORE_THRESHOLD:  int = _env_int("CRITICAL_SCORE_THRESHOLD",  15)


# ══════════════════════════════════════════════════════════════════════════════
# تنظیمات ذخیره‌سازی
# ══════════════════════════════════════════════════════════════════════════════
MAX_NEWS_PER_RUN: int = _env_int("MAX_NEWS_PER_RUN", 30)
MAX_STORED_NEWS:  int = _env_int("MAX_STORED_NEWS", 1000)


# ══════════════════════════════════════════════════════════════════════════════
# تنظیمات ارسال
# ══════════════════════════════════════════════════════════════════════════════
DELAY_BETWEEN_SENDS:  float = _env_float("DELAY_BETWEEN_SENDS", 4.0)
SEND_RETRY_COUNT:     int   = _env_int("SEND_RETRY_COUNT",    2)
SEND_RETRY_DELAY:     float = _env_float("SEND_RETRY_DELAY",  3.0)
CAPTION_MAX_LEN:      int   = _env_int("CAPTION_MAX_LEN",  1020)
MESSAGE_MAX_LEN:      int   = _env_int("MESSAGE_MAX_LEN",  4000)
IMAGE_CHECK_TIMEOUT:  int   = _env_int("IMAGE_CHECK_TIMEOUT", 5)


# ══════════════════════════════════════════════════════════════════════════════
# مدل FeedConfig
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class FeedConfig:
    """پیکربندی یک منبع RSS."""
    name:          str
    url:           str
    dedicated:     bool = True    # اختصاصی محیط‌زیست → آستانه پایین‌تر
    skip_on_error: bool = False   # اگر True: خطا را log کن، ادامه بده


# ══════════════════════════════════════════════════════════════════════════════
# ۱۳ فید RSS اختصاصی محیط‌زیست
# ══════════════════════════════════════════════════════════════════════════════
RSS_FEEDS: list[FeedConfig] = [
    FeedConfig(
        name="مهر — محیط‌زیست",
        url="https://www.mehrnews.com/rss/tp/64",
        skip_on_error=True,          # BOM/bozo شناخته‌شده
    ),
    FeedConfig(
        name="همشهری آنلاین — محیط‌زیست",
        url="https://www.hamshahrionline.ir/rss/tp/584",
    ),
    FeedConfig(
        name="خبرآنلاین — محیط‌زیست",
        url="https://www.khabaronline.ir/rss/tp/44",
    ),
    FeedConfig(
        name="خبرآنلاین — طبیعت",
        url="https://www.khabaronline.ir/rss/tp/75",
    ),
    FeedConfig(
        name="سلامت نیوز — محیط‌زیست",
        url="https://www.salamatnews.com/rss/tp/11",
    ),
    FeedConfig(
        name="سلامت نیوز — اکوسیستم",
        url="https://www.salamatnews.com/rss/pl/240",
    ),
    FeedConfig(
        name="ایمنا — محیط‌زیست",
        url="https://www.imna.ir/rss/tp/153",
    ),
    FeedConfig(
        name="صدا و سیما — محیط‌زیست اجتماعی",
        url="https://www.iribnews.ir/fa/rss/7/39",
    ),
    FeedConfig(
        name="صدا و سیما — محیط‌زیست اقتصادی",
        url="https://www.iribnews.ir/fa/rss/6/8",
    ),
    FeedConfig(
        name="صدا و سیما — آب و انرژی",
        url="https://www.iribnews.ir/fa/rss/6/46",
    ),
    FeedConfig(
        name="باشگاه خبرنگاران — محیط‌زیست",
        url="https://www.yjc.ir/fa/rss/5/74",
        skip_on_error=True,          # HTTP 403 از GitHub Actions
    ),
    FeedConfig(
        name="روزنامه حیات — محیط‌زیست",
        url="https://www.hayat.ir/rss/tp/94",
        skip_on_error=True,
    ),
    FeedConfig(
        name="اطلاعات — گردشگری و محیط‌زیست",
        url="https://www.ettelaat.com/rss/tp/65",
        skip_on_error=True,
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# User-Agents (چرخشی در collector)
# ══════════════════════════════════════════════════════════════════════════════
USER_AGENTS: list[str] = [
    # مرورگرهای واقعی
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15",

    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) "
    "Gecko/20100101 Firefox/115.0",

    # Bot-friendly
    "feedfetcher-google; (+http://www.google.com/feedfetcher.html)",
    "Googlebot/2.1 (+http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Baiduspider/2.0)",
]


# ══════════════════════════════════════════════════════════════════════════════
# دسته‌بندی‌های محیط‌زیستی
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CategoryConfig:
    key:      str
    fa:       str
    emoji:    str
    color:    str
    keywords: tuple[str, ...]


CATEGORIES: list[CategoryConfig] = [
    CategoryConfig(
        key="air_water_soil",
        fa="آلودگی هوا، آب و خاک",
        emoji="🌬️",
        color="#ef4444",
        keywords=(
            "آلودگی", "آلوده", "هوای آلوده", "خاک آلوده", "آب آلوده",
            "فاضلاب", "پساب", "دود", "ذرات معلق", "PM2.5", "PM10",
            "اکسید نیتروژن", "دی‌اکسید گوگرد", "ازن", "سرب", "جیوه",
            "کادمیوم", "پلاستیک", "زباله", "پسماند", "انباشت زباله",
            "آلودگی صوتی", "نیترات", "فسفات", "شوینده", "سم کشاورزی",
        ),
    ),
    CategoryConfig(
        key="wildlife",
        fa="حیات وحش و تنوع زیستی",
        emoji="🐆",
        color="#f97316",
        keywords=(
            "حیات وحش", "یوزپلنگ", "پلنگ", "گرگ", "خرس", "آهو",
            "گوزن", "کرکس", "عقاب", "فلامینگو", "پرنده", "ماهی",
            "مرجان", "تنوع زیستی", "گونه در خطر", "انقراض",
            "قاچاق حیوانات", "صید غیرمجاز", "شکار غیرمجاز",
            "حفاظت گونه", "پارک ملی", "زیستگاه",
        ),
    ),
    CategoryConfig(
        key="water_wetlands",
        fa="تالاب‌ها، دریاها و منابع آب",
        emoji="🌊",
        color="#3b82f6",
        keywords=(
            "تالاب", "دریاچه ارومیه", "دریای خزر", "خلیج فارس",
            "دریای عمان", "رودخانه", "بحران آب", "کم‌آبی",
            "خشکسالی", "آب زیرزمینی", "آبخوان", "سد",
            "منابع آبی", "تالاب انزلی", "هور العظیم",
            "شوری آب", "آب شرب",
        ),
    ),
    CategoryConfig(
        key="climate",
        fa="تغییر اقلیم و بحران‌های طبیعی",
        emoji="🌡️",
        color="#8b5cf6",
        keywords=(
            "تغییر اقلیم", "گرمایش زمین", "کربن", "دی‌اکسید کربن",
            "گازهای گلخانه‌ای", "سیلاب", "طوفان", "گرد و غبار",
            "ریزگرد", "آتش‌سوزی", "موج گرما", "COP", "پاریس",
            "کاهش کربن", "جذب کربن",
        ),
    ),
    CategoryConfig(
        key="forests",
        fa="جنگل‌ها، مراتع و منابع طبیعی",
        emoji="🌲",
        color="#22c55e",
        keywords=(
            "جنگل", "مرتع", "جنگل‌زدایی", "قطع درخت",
            "آتش‌سوزی جنگل", "منابع طبیعی", "حوضه آبخیز",
            "جنگل هیرکانی", "ارسباران", "زاگرس", "معدن",
            "استخراج معدن", "درختکاری",
        ),
    ),
    CategoryConfig(
        key="policy",
        fa="سیاست‌ها، قوانین و سازمان",
        emoji="🏛️",
        color="#64748b",
        keywords=(
            "سازمان حفاظت", "قانون محیط زیست", "مصوبه",
            "معاونت محیط زیست", "بودجه محیط زیست",
            "آیین‌نامه زیست‌محیطی", "جریمه زیست‌محیطی",
            "توافقنامه محیط زیست", "UNEP", "یونپ",
            "برنامه محیط زیست",
        ),
    ),
    CategoryConfig(
        key="sustainable",
        fa="توسعه پایدار و انرژی پاک",
        emoji="♻️",
        color="#10b981",
        keywords=(
            "توسعه پایدار", "انرژی تجدیدپذیر", "خورشیدی", "بادی",
            "برق سبز", "هیدروژن سبز", "بیوگاز", "بازیافت",
            "اقتصاد چرخشی", "ساختمان سبز", "حمل‌ونقل سبز",
            "پنل خورشیدی", "توربین بادی", "صرفه‌جویی انرژی",
            "ISO 14001",
        ),
    ),
]

# دیکشنری سریع: key → CategoryConfig
CATEGORY_MAP: dict[str, CategoryConfig] = {c.key: c for c in CATEGORIES}


# ══════════════════════════════════════════════════════════════════════════════
# بلک‌لیست (رد فوری — نباید با کلمات محیط‌زیستی ترکیب بشوند)
# ══════════════════════════════════════════════════════════════════════════════
BLACKLIST: list[str] = [
    # ورزش
    "فوتبال", "والیبال", "بسکتبال", "کشتی", "وزنه‌برداری",
    "لیگ برتر", "جام جهانی", "المپیک", "مسابقات ورزشی",
    "تیم ملی فوتبال", "لیگ فوتبال",
    # مالی (بدون ترکیب محیط‌زیستی)
    "بازار سهام", "بورس اوراق", "سکه طلا", "قیمت دلار",
    "نرخ ارز", "صندوق سرمایه‌گذاری",
    # حوادث ترافیکی
    "تصادف رانندگی", "واژگونی خودرو", "تلفات جاده",
    # فرهنگی-هنری (بدون ربط محیط‌زیستی)
    "جشنواره فیلم", "اکران فیلم", "موسیقی پاپ",
    "مجلس شعر", "نمایشگاه نقاشی",
]


# ══════════════════════════════════════════════════════════════════════════════
# کلمات کلیدی وزن‌دار
# ══════════════════════════════════════════════════════════════════════════════
KEYWORDS: dict[str, int] = {
    # ─── وزن ۵ ───────────────────────────────────────────────────────────────
    "محیط زیست":           5,
    "محیط‌زیست":           5,
    "حفاظت محیط":          5,
    "آلودگی":              5,
    "بحران زیست‌محیطی":   5,
    "فاجعه زیست‌محیطی":   5,
    "انقراض":              5,
    "یوزپلنگ":             5,
    "دریاچه ارومیه":       5,
    "بحران آب":            5,
    "گرمایش زمین":         5,
    "تغییر اقلیم":         5,
    "جنگل‌زدایی":          5,
    "تالاب":               5,

    # ─── وزن ۴ ───────────────────────────────────────────────────────────────
    "آلوده":               4,
    "زیست‌بوم":            4,
    "اکوسیستم":            4,
    "تنوع زیستی":          4,
    "حیات وحش":            4,
    "منابع طبیعی":         4,
    "آب زیرزمینی":         4,
    "فرسایش خاک":          4,
    "انرژی تجدیدپذیر":     4,
    "توسعه پایدار":         4,
    "گازهای گلخانه‌ای":    4,
    "ریزگرد":              4,
    "گرد و غبار":           4,
    "آتش‌سوزی جنگل":       4,
    "خشکسالی":             4,
    "سیلاب":               4,
    "پسماند":              4,
    "فاضلاب":              4,

    # ─── وزن ۳ ───────────────────────────────────────────────────────────────
    "جنگل":                3,
    "مرتع":                3,
    "دریاچه":              3,
    "رودخانه":             3,
    "آبخوان":              3,
    "پلنگ":                3,
    "گرگ":                 3,
    "عقاب":                3,
    "کرکس":                3,
    "فلامینگو":            3,
    "صید غیرمجاز":         3,
    "شکار غیرمجاز":        3,
    "قاچاق حیوانات":       3,
    "بازیافت":             3,
    "کربن":                3,
    "دی‌اکسید کربن":       3,
    "UNEP":                3,
    "یونپ":                3,
    "COP":                 3,
    "پارک ملی":            3,
    "منطقه حفاظت‌شده":     3,
    "زیستگاه":             3,
    "خورشیدی":             3,
    "بادی":                3,
    "ISO 14001":           3,
    "ازن":                 3,

    # ─── وزن ۲ ───────────────────────────────────────────────────────────────
    "درخت":                2,
    "دریا":                2,
    "طبیعت":               2,
    "اقلیم":               2,
    "معدن":                2,
    "پتروشیمی":            2,
    "پرنده":               2,
    "ماهی":                2,
    "مرجان":               2,
    "گونه":                2,
    "آبیاری":              2,
    "خاک":                 2,
    "هوا":                 2,
    "آب":                  2,
    "سبز":                 2,
    "پاک":                 2,

    # ─── وزن ۱ ───────────────────────────────────────────────────────────────
    "سازمان":              1,
    "معاونت":              1,
    "قانون":               1,
    "مصوبه":               1,
    "برنامه":              1,
    "پایش":                1,
    "رصد":                 1,
    "ارزیابی":             1,
    "مدیریت":              1,
}


# ══════════════════════════════════════════════════════════════════════════════
# امضای ربات
# ══════════════════════════════════════════════════════════════════════════════
BOT_SIGNATURE: str = (
    "🌿 <b>سامانه پایش هوشمند اخبار محیط‌زیست</b>\n"
    "🏛 روابط‌عمومی سازمان حفاظت محیط‌زیست ایران"
)


# ══════════════════════════════════════════════════════════════════════════════
# اعتبارسنجی هنگام import
# ══════════════════════════════════════════════════════════════════════════════
def _validate() -> None:
    """
    بررسی مقادیر حیاتی هنگام import.
    فقط WARNING می‌دهد — پروژه را متوقف نمی‌کند
    تا در تست محلی بدون secrets هم کار کند.
    """
    warnings: list[str] = []

    if not TELEGRAM_BOT_TOKEN and not BALE_BOT_TOKEN:
        warnings.append("هیچ توکن ربات (تلگرام یا بله) تنظیم نشده — ارسال غیرفعال")

    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY تنظیم نشده — تحلیل AI غیرفعال")

    if AI_MAX_PER_RUN > AI_MAX_PER_DAY:
        warnings.append(
            f"AI_MAX_PER_RUN ({AI_MAX_PER_RUN}) > AI_MAX_PER_DAY ({AI_MAX_PER_DAY})"
        )

    if SCORE_THRESHOLD_DEDICATED > SCORE_THRESHOLD_GENERAL:
        warnings.append(
            "SCORE_THRESHOLD_DEDICATED از SCORE_THRESHOLD_GENERAL بیشتر است — "
            "منابع اختصاصی سخت‌تر فیلتر می‌شوند"
        )

    for w in warnings:
        log.warning(f"⚠️  config: {w}")


_validate()
