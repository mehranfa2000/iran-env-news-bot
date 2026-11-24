# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/filter.py  ·  v4.1  ·  فیلتر ۴ لایه محیط‌زیستی                       ║
# ║  اعتبارسنجی → لیست‌سیاه → امتیاز کلیدواژه → دسته‌بندی + بحرانی            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import logging
import re
from typing import Optional

from src.collector import RawArticle
from src.config    import (
    CRITICAL_SCORE_THRESHOLD,
    DEFAULT_CATEGORY,
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. لیست سیاه — کلیدواژه‌های غیرمحیط‌زیستی
# ══════════════════════════════════════════════════════════════════════════════

_BLACKLIST: list[str] = [
    # سیاسی و نظامی
    "انتخابات", "نامزد", "رأی", "مجلس", "دولت", "وزیر", "رئیس‌جمهور",
    "نظامی", "سپاه", "ارتش", "موشک", "تسلیحات", "جنگ", "حمله",
    "تحریم", "دیپلماسی", "سفارت", "وزارت خارجه",
    # اقتصادی غیرمرتبط
    "بورس", "سهام", "ارز", "دلار", "طلا", "بانک", "وام", "بیمه",
    "بازار", "تورم", "نرخ سود", "سرمایه‌گذاری خارجی",
    # ورزشی
    "فوتبال", "والیبال", "بسکتبال", "ورزشکار", "مسابقه", "لیگ",
    "جام", "تیم ملی", "گل", "باخت", "برد",
    # سرگرمی
    "فیلم", "سریال", "بازیگر", "کنسرت", "موسیقی", "جشنواره فیلم",
    "هنرمند", "خواننده",
    # حوادث غیرمحیط‌زیستی
    "تصادف", "سرقت", "قتل", "جرم", "دستگیری", "زندان", "دادگاه",
    # فناوری غیرمرتبط
    "گوشی", "لپ‌تاپ", "بازی کامپیوتری", "شبکه اجتماعی",
]

_BLACKLIST_PATTERN = re.compile(
    "|".join(re.escape(w) for w in _BLACKLIST)
)

# ══════════════════════════════════════════════════════════════════════════════
#  ۲. کلیدواژه‌های محیط‌زیستی وزن‌دار — ۲۰۰+ کلیدواژه
# ══════════════════════════════════════════════════════════════════════════════

# فرمت: (کلیدواژه، امتیاز، دسته)
_KEYWORDS: list[tuple[str, int, str]] = [

    # ══ آلودگی هوا، آب و خاک (air_water_soil) ══════════════════════════════
    ("آلودگی هوا",         10, "air_water_soil"),
    ("آلودگی آب",          10, "air_water_soil"),
    ("آلودگی خاک",         10, "air_water_soil"),
    ("شاخص کیفیت هوا",    10, "air_water_soil"),
    ("AQI",                 8, "air_water_soil"),
    ("ریزگرد",             10, "air_water_soil"),
    ("گرد و غبار",          8, "air_water_soil"),
    ("ذرات معلق",           8, "air_water_soil"),
    ("PM2.5",               8, "air_water_soil"),
    ("PM10",                7, "air_water_soil"),
    ("هوای آلوده",          9, "air_water_soil"),
    ("هوای ناسالم",         9, "air_water_soil"),
    ("کیفیت هوا",           7, "air_water_soil"),
    ("آلاینده",             7, "air_water_soil"),
    ("دی‌اکسید کربن",       7, "air_water_soil"),
    ("دی اکسید گوگرد",     7, "air_water_soil"),
    ("اکسید نیتروژن",       7, "air_water_soil"),
    ("کربن",                4, "air_water_soil"),
    ("فاضلاب",              7, "air_water_soil"),
    ("پساب",                7, "air_water_soil"),
    ("آب آلوده",            9, "air_water_soil"),
    ("آلودگی صنعتی",        9, "air_water_soil"),
    ("پالایشگاه",           5, "air_water_soil"),
    ("نفت",                 4, "air_water_soil"),
    ("نشت نفت",            10, "air_water_soil"),
    ("سرب",                 6, "air_water_soil"),
    ("جیوه",                7, "air_water_soil"),
    ("کادمیوم",             7, "air_water_soil"),
    ("آرسنیک",              7, "air_water_soil"),
    ("پلاستیک",             5, "air_water_soil"),
    ("میکروپلاستیک",        8, "air_water_soil"),
    ("زباله",               4, "air_water_soil"),
    ("پسماند",              6, "air_water_soil"),
    ("دفن زباله",           7, "air_water_soil"),
    ("بازیافت",             5, "air_water_soil"),

    # ══ حیات وحش و تنوع زیستی (wildlife) ═══════════════════════════════════
    ("یوزپلنگ",            12, "wildlife"),
    ("پلنگ",               10, "wildlife"),
    ("ببر",                10, "wildlife"),
    ("خرس",                 8, "wildlife"),
    ("گرگ",                 7, "wildlife"),
    ("شیر",                 8, "wildlife"),
    ("حیات وحش",           10, "wildlife"),
    ("گونه در خطر",        12, "wildlife"),
    ("گونه‌های در معرض انقراض", 12, "wildlife"),
    ("انقراض",             10, "wildlife"),
    ("تنوع زیستی",         10, "wildlife"),
    ("اکوسیستم",            8, "wildlife"),
    ("پرنده",               6, "wildlife"),
    ("پرندگان مهاجر",      10, "wildlife"),
    ("صید غیرمجاز",        10, "wildlife"),
    ("شکار غیرمجاز",       10, "wildlife"),
    ("شکار",                5, "wildlife"),
    ("قاچاق حیوانات",      12, "wildlife"),
    ("پناهگاه حیات وحش",   10, "wildlife"),
    ("پارک ملی",            8, "wildlife"),
    ("حفاظت از گونه",      10, "wildlife"),
    ("مناطق حفاظت‌شده",     8, "wildlife"),
    ("آهو",                 7, "wildlife"),
    ("گوزن",                7, "wildlife"),
    ("کرکس",                7, "wildlife"),
    ("عقاب",                7, "wildlife"),
    ("لاک‌پشت دریایی",      9, "wildlife"),
    ("نهنگ",                8, "wildlife"),
    ("دلفین",               7, "wildlife"),
    ("فوک",                 8, "wildlife"),
    ("اوتر",                8, "wildlife"),
    ("سمور",                8, "wildlife"),
    ("زیستگاه",             7, "wildlife"),
    ("کریدور زیستی",        9, "wildlife"),
    ("بیوسفر",              7, "wildlife"),

    # ══ تالاب‌ها، دریاها و منابع آب (water_wetlands) ════════════════════════
    ("دریاچه ارومیه",      15, "water_wetlands"),
    ("هامون",              12, "water_wetlands"),
    ("گاوخونی",            12, "water_wetlands"),
    ("بختگان",             10, "water_wetlands"),
    ("پریشان",             10, "water_wetlands"),
    ("شادگان",             10, "water_wetlands"),
    ("تالاب",              10, "water_wetlands"),
    ("دریاچه",              7, "water_wetlands"),
    ("دریای خزر",          10, "water_wetlands"),
    ("خلیج فارس",          10, "water_wetlands"),
    ("دریای عمان",         10, "water_wetlands"),
    ("رودخانه",             7, "water_wetlands"),
    ("زاینده‌رود",         12, "water_wetlands"),
    ("کارون",              10, "water_wetlands"),
    ("کرخه",                9, "water_wetlands"),
    ("ارس",                 8, "water_wetlands"),
    ("آب‌های زیرزمینی",    10, "water_wetlands"),
    ("سفره آب زیرزمینی",   10, "water_wetlands"),
    ("خشک شدن",             8, "water_wetlands"),
    ("کم‌آبی",              9, "water_wetlands"),
    ("خشکسالی",            10, "water_wetlands"),
    ("بحران آب",           12, "water_wetlands"),
    ("کمبود آب",           10, "water_wetlands"),
    ("حوضه آبریز",          8, "water_wetlands"),
    ("سد",                  5, "water_wetlands"),
    ("آبیاری",              4, "water_wetlands"),
    ("منابع آب",            7, "water_wetlands"),
    ("رامسر",               8, "water_wetlands"),
    ("آلودگی دریا",        10, "water_wetlands"),
    ("ماهی",                4, "water_wetlands"),
    ("صید",                 4, "water_wetlands"),
    ("شیلات",               5, "water_wetlands"),

    # ══ تغییر اقلیم و بحران‌های طبیعی (climate) ════════════════════════════
    ("تغییر اقلیم",        12, "climate"),
    ("گرمایش زمین",        12, "climate"),
    ("گازهای گلخانه‌ای",   10, "climate"),
    ("اثر گلخانه‌ای",      10, "climate"),
    ("کربن دی اکسید",       7, "climate"),
    ("سیل",                 8, "climate"),
    ("سیلاب",               9, "climate"),
    ("زلزله",               6, "climate"),
    ("آتشفشان",             7, "climate"),
    ("گرمای بی‌سابقه",     10, "climate"),
    ("موج گرما",            10, "climate"),
    ("یخبندان",             7, "climate"),
    ("برف",                 3, "climate"),
    ("طوفان",               7, "climate"),
    ("گرد و غبار",          7, "climate"),
    ("بیابان‌زایی",        10, "climate"),
    ("فرسایش خاک",          9, "climate"),
    ("ذوب یخ",             10, "climate"),
    ("یخچال‌های طبیعی",    10, "climate"),
    ("بلایای طبیعی",        8, "climate"),
    ("اقلیم",               5, "climate"),
    ("COP",                 7, "climate"),
    ("پاریس",               3, "climate"),
    ("کیوتو",               6, "climate"),
    ("IPCC",                8, "climate"),
    ("اقتصاد کربنی",        8, "climate"),

    # ══ جنگل‌ها، مراتع و منابع طبیعی (forests) ═════════════════════════════
    ("جنگل",                8, "forests"),
    ("جنگل‌زدایی",         10, "forests"),
    ("قطع درخت",           10, "forests"),
    ("آتش‌سوزی جنگل",      12, "forests"),
    ("آتش‌سوزی",            7, "forests"),
    ("مرتع",                7, "forests"),
    ("منابع طبیعی",         7, "forests"),
    ("درخت‌کاری",           7, "forests"),
    ("جنگل هیرکانی",       12, "forests"),
    ("جنگل‌های زاگرس",     12, "forests"),
    ("بلوط",                7, "forests"),
    ("درخت",                4, "forests"),
    ("فضای سبز",            5, "forests"),
    ("بیشه",                6, "forests"),
    ("سرانه فضای سبز",      7, "forests"),
    ("کویر",                7, "forests"),
    ("بیابان",              7, "forests"),
    ("ماسه‌های روان",       9, "forests"),
    ("احیای مراتع",         9, "forests"),
    ("سیل‌بندی",            7, "forests"),
    ("آبخیزداری",           8, "forests"),
    ("خاک",                 3, "forests"),

    # ══ سیاست‌ها، قوانین و سازمان (policy) ═════════════════════════════════
    ("سازمان محیط‌زیست",   10, "policy"),
    ("سازمان حفاظت",        8, "policy"),
    ("وزارت نیرو",          4, "policy"),
    ("قانون محیط‌زیست",    10, "policy"),
    ("استاندارد زیست‌محیطی", 9, "policy"),
    ("ارزیابی زیست‌محیطی",  9, "policy"),
    ("EIA",                 8, "policy"),
    ("مجوز زیست‌محیطی",     8, "policy"),
    ("جریمه زیست‌محیطی",   10, "policy"),
    ("UNEP",                8, "policy"),
    ("برنامه ملی",          4, "policy"),
    ("سند ملی",             4, "policy"),
    ("پروتکل",              5, "policy"),
    ("معاهده",              5, "policy"),
    ("کنوانسیون",           7, "policy"),
    ("CITES",               9, "policy"),
    ("رامسر",               7, "policy"),
    ("اجلاس",               4, "policy"),
    ("بودجه محیط‌زیست",     8, "policy"),
    ("کارگروه",             3, "policy"),

    # ══ توسعه پایدار و انرژی پاک (sustainable) ═════════════════════════════
    ("انرژی تجدیدپذیر",    10, "sustainable"),
    ("انرژی خورشیدی",       9, "sustainable"),
    ("پنل خورشیدی",         8, "sustainable"),
    ("انرژی بادی",          9, "sustainable"),
    ("توربین بادی",         8, "sustainable"),
    ("انرژی سبز",           8, "sustainable"),
    ("برق تجدیدپذیر",       8, "sustainable"),
    ("هیدروژن سبز",         9, "sustainable"),
    ("خودروی برقی",         7, "sustainable"),
    ("حمل‌ونقل پاک",        8, "sustainable"),
    ("ساختمان سبز",         7, "sustainable"),
    ("توسعه پایدار",        8, "sustainable"),
    ("اقتصاد سبز",          8, "sustainable"),
    ("اقتصاد چرخشی",        8, "sustainable"),
    ("کاهش کربن",           8, "sustainable"),
    ("خنثی از نظر کربن",    9, "sustainable"),
    ("net zero",            9, "sustainable"),
    ("بهره‌وری انرژی",      7, "sustainable"),
    ("صرفه‌جویی انرژی",     6, "sustainable"),
    ("پانل خورشیدی",        7, "sustainable"),

    # ══ کلیدواژه‌های عمومی محیط‌زیست ════════════════════════════════════════
    ("محیط زیست",           6, DEFAULT_CATEGORY),
    ("محیط‌زیست",           6, DEFAULT_CATEGORY),
    ("زیست‌محیطی",          6, DEFAULT_CATEGORY),
    ("طبیعت",               4, DEFAULT_CATEGORY),
    ("حفاظت",               3, DEFAULT_CATEGORY),
    ("اکولوژی",             7, DEFAULT_CATEGORY),
    ("اکو",                 3, DEFAULT_CATEGORY),
    ("سبز",                 2, DEFAULT_CATEGORY),
    ("پایدار",              3, DEFAULT_CATEGORY),
    ("آلودگی",              5, DEFAULT_CATEGORY),
    ("بحران زیست‌محیطی",   10, DEFAULT_CATEGORY),
    ("فاجعه زیست‌محیطی",   12, DEFAULT_CATEGORY),
    ("مخاطرات زیست‌محیطی",  9, DEFAULT_CATEGORY),
]


def _build_keyword_pattern(keyword: str) -> re.Pattern:
    """
    ساخت regex برای کلیدواژه.
    برای کلیدواژه‌های ≤ ۴ کاراکتر → word boundary برای جلوگیری از false positive.
    مثال: «دام» نباید در «اقدامات» پیدا شود.
    """
    escaped = re.escape(keyword)
    if len(keyword) <= 4:
        return re.compile(r"(?<!\w)" + escaped + r"(?!\w)")
    return re.compile(escaped)


# ساخت یک بار در زمان import
_KEYWORD_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    (_build_keyword_pattern(kw), score, cat)
    for kw, score, cat in _KEYWORDS
]

# ══════════════════════════════════════════════════════════════════════════════
#  ۳. فیلتر اصلی
# ══════════════════════════════════════════════════════════════════════════════

def _score_article(raw: RawArticle) -> tuple[int, str]:
    """
    محاسبه امتیاز و دسته‌بندی برای یک خبر.

    Returns:
        (امتیاز_کل، بهترین_دسته)
    """
    text = f"{raw.title} {raw.summary} {' '.join(raw.tags)}".lower()

    total_score = 0
    category_scores: dict[str, int] = {}

    for pattern, score, category in _KEYWORD_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            match_score = score * len(matches)
            total_score += match_score
            category_scores[category] = category_scores.get(category, 0) + match_score

    # بهترین دسته بر اساس بالاترین امتیاز
    if category_scores:
        # حذف دسته پیش‌فرض اگر دسته‌های بهتری وجود دارند
        specific = {k: v for k, v in category_scores.items() if k != DEFAULT_CATEGORY}
        if specific:
            best_category = max(specific, key=lambda k: specific[k])
        else:
            best_category = DEFAULT_CATEGORY
    else:
        best_category = DEFAULT_CATEGORY

    return total_score, best_category


def filter_news(
    articles: list[RawArticle],
) -> list[tuple[RawArticle, int, str, bool]]:
    """
    فیلتر ۴ لایه:
    لایه ۱: اعتبارسنجی فیلدها (عنوان + لینک لازم)
    لایه ۲: لیست سیاه (کلیدواژه‌های غیرمحیط‌زیستی)
    لایه ۳: امتیاز کلیدواژه (حداقل آستانه)
    لایه ۴: دسته‌بندی + علامت بحرانی

    Returns:
        list of (RawArticle, score, category, is_critical)
    """
    total      = len(articles)
    l1_failed  = 0
    l2_failed  = 0
    l3_failed  = 0
    approved   = 0

    results: list[tuple[RawArticle, int, str, bool]] = []

    for raw in articles:
        # ── لایه ۱: اعتبارسنجی ──────────────────────────────────────────────
        if not raw.title or not raw.link:
            l1_failed += 1
            continue

        # ── لایه ۲: لیست سیاه ───────────────────────────────────────────────
        combined_text = f"{raw.title} {raw.summary}"
        if _BLACKLIST_PATTERN.search(combined_text):
            # اگر در عنوان کلیدواژه قوی محیط‌زیستی داشت → از لیست سیاه رد می‌شود
            has_strong_env = any(
                p.search(raw.title.lower())
                for p, score, _ in _KEYWORD_PATTERNS
                if score >= 8
            )
            if not has_strong_env:
                l2_failed += 1
                continue

        # ── لایه ۳: امتیاز کلیدواژه ─────────────────────────────────────────
        score, category = _score_article(raw)
        threshold = SCORE_THRESHOLD_DEDICATED if raw.dedicated else SCORE_THRESHOLD_GENERAL

        if score < threshold:
            l3_failed += 1
            continue

        # ── لایه ۴: دسته‌بندی + بحرانی ──────────────────────────────────────
        is_critical = score >= CRITICAL_SCORE_THRESHOLD

        results.append((raw, score, category, is_critical))
        approved += 1

    logger.info(
        "🔍 فیلتر: %d کل | %d فیلد | %d لیست‌سیاه | %d امتیاز کم | %d تأیید",
        total, l1_failed, l2_failed, l3_failed, approved
    )

    # مرتب‌سازی: بحرانی > امتیاز بالا
    results.sort(key=lambda t: (t[3], t[1]), reverse=True)
    return results
