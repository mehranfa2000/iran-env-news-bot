"""
filter.py — v4.0
فیلتر ۴ لایه با ۲۰۰+ کلمه‌کلیدی وزن‌دار + دسته‌بندی هوشمند
لایه ۱: اعتبارسنجی فیلد
لایه ۲: بلک‌لیست (غیر محیط‌زیستی)
لایه ۳: امتیازدهی وزن‌دار با regex مرزی
لایه ۴: دسته‌بندی + تشخیص بحران
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    CATEGORIES,
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
    CRITICAL_SCORE_THRESHOLD,
    Category,
)
from src.collector import RawNewsItem

logger = logging.getLogger("filter")

# ═══════════════════════════════════════════════════════════════
# ۱) ساختار خبر فیلترشده
# ═══════════════════════════════════════════════════════════════
@dataclass
class FilteredNewsItem:
    uid: str
    title: str
    summary: str
    link: str
    source: str
    published_dt: object         # datetime UTC
    image_url: Optional[str]
    category: Category
    score: int
    critical: bool
    matched_keywords: list[str]
    feed_dedicated: bool
    feed_priority: int
    # پر می‌شود توسط analyzer:
    ai_summary: Optional[str]      = None
    ai_analysis: Optional[dict]    = None


# ═══════════════════════════════════════════════════════════════
# ۲) کلمات کلیدی وزن‌دار (۲۰۰+)
#    فرمت: ("کلمه", وزن, [دسته‌های مرتبط])
# ═══════════════════════════════════════════════════════════════
WEIGHTED_KEYWORDS: list[tuple[str, int, list[str]]] = [

    # ── آلودگی هوا/آب/خاک — وزن بالا ────────────────────────
    ("آلودگی هوا",          10, ["air_water_soil"]),
    ("آلودگی آب",           10, ["air_water_soil", "water_wetlands"]),
    ("آلودگی خاک",          10, ["air_water_soil"]),
    ("آلودگی صوتی",          6, ["air_water_soil"]),
    ("آلودگی نوری",          5, ["air_water_soil"]),
    ("شاخص کیفیت هوا",      10, ["air_water_soil"]),
    ("AQI",                  8, ["air_water_soil"]),
    ("ذرات معلق",            9, ["air_water_soil"]),
    ("PM2.5",               10, ["air_water_soil"]),
    ("PM10",                 8, ["air_water_soil"]),
    ("کربن‌مونوکسید",        8, ["air_water_soil"]),
    ("دی‌اکسید گوگرد",       7, ["air_water_soil"]),
    ("اکسید نیتروژن",        7, ["air_water_soil"]),
    ("ازن",                  6, ["air_water_soil"]),
    ("هوای ناسالم",          9, ["air_water_soil"]),
    ("هوای آلوده",           9, ["air_water_soil"]),
    ("وارونگی دما",          8, ["air_water_soil"]),
    ("وارونگی هوا",          8, ["air_water_soil"]),
    ("کارخانه آلاینده",      8, ["air_water_soil"]),
    ("صنعت آلاینده",         7, ["air_water_soil"]),
    ("فاضلاب",               7, ["air_water_soil", "water_wetlands"]),
    ("پساب",                 7, ["air_water_soil", "water_wetlands"]),
    ("پسماند",               7, ["air_water_soil"]),
    ("زباله",                5, ["air_water_soil"]),
    ("مواد زائد",            6, ["air_water_soil"]),
    ("سرب",                  7, ["air_water_soil"]),
    ("جیوه",                 8, ["air_water_soil"]),
    ("کادمیوم",              7, ["air_water_soil"]),
    ("آرسنیک",               7, ["air_water_soil"]),
    ("نیترات",               6, ["air_water_soil", "water_wetlands"]),
    ("فسفر",                 5, ["air_water_soil", "water_wetlands"]),
    ("هیدروکربن",            7, ["air_water_soil"]),
    ("آلاینده",              8, ["air_water_soil"]),
    ("سم",                   6, ["air_water_soil", "wildlife"]),
    ("سموم",                 7, ["air_water_soil", "wildlife"]),
    ("کود شیمیایی",          6, ["air_water_soil"]),
    ("آفت‌کش",               7, ["air_water_soil", "wildlife"]),
    ("سطح سرب خون",          8, ["air_water_soil"]),
    ("آلودگی صنعتی",         9, ["air_water_soil"]),
    ("پالایشگاه",            6, ["air_water_soil"]),
    ("نیروگاه حرارتی",       6, ["air_water_soil"]),
    ("آلودگی نفتی",          9, ["air_water_soil", "water_wetlands"]),
    ("نشت نفت",              9, ["air_water_soil", "water_wetlands"]),
    ("ریزگرد",               9, ["air_water_soil"]),
    ("گرد و غبار",           8, ["air_water_soil"]),
    ("طوفان گرد",            7, ["air_water_soil", "climate"]),

    # ── حیات وحش ─────────────────────────────────────────────
    ("حیات وحش",             10, ["wildlife"]),
    ("یوزپلنگ",              10, ["wildlife"]),
    ("ببر",                   9, ["wildlife"]),
    ("پلنگ",                  9, ["wildlife"]),
    ("خرس",                   8, ["wildlife"]),
    ("گرگ",                   7, ["wildlife"]),
    ("گوزن",                  8, ["wildlife"]),
    ("کرکس",                  8, ["wildlife"]),
    ("عقاب",                  8, ["wildlife"]),
    ("لاک‌پشت دریایی",        9, ["wildlife", "water_wetlands"]),
    ("فلامینگو",              8, ["wildlife", "water_wetlands"]),
    ("پرنده مهاجر",           8, ["wildlife"]),
    ("پرندگان مهاجر",         8, ["wildlife"]),
    ("تنوع زیستی",           10, ["wildlife"]),
    ("تنوع گونه‌ای",          9, ["wildlife"]),
    ("گونه در خطر",          10, ["wildlife"]),
    ("گونه منقرض",           10, ["wildlife"]),
    ("انقراض",               10, ["wildlife"]),
    ("قاچاق حیوانات",        10, ["wildlife"]),
    ("شکار غیرمجاز",         10, ["wildlife"]),
    ("صید غیرمجاز",          10, ["wildlife"]),
    ("ممنوعیت شکار",          7, ["wildlife"]),
    ("مناطق شکار ممنوع",      7, ["wildlife"]),
    ("کریدور زیستی",          8, ["wildlife"]),
    ("زیستگاه",               8, ["wildlife"]),
    ("اکوسیستم",              8, ["wildlife"]),
    ("گونه بومی",             7, ["wildlife"]),
    ("گونه غیربومی",          7, ["wildlife"]),
    ("گونه مهاجم",            7, ["wildlife"]),
    ("ماهی",                  5, ["wildlife", "water_wetlands"]),
    ("آبزیان",                7, ["wildlife", "water_wetlands"]),
    ("مرجان",                 8, ["wildlife", "water_wetlands"]),
    ("دلفین",                 8, ["wildlife", "water_wetlands"]),
    ("نهنگ",                  8, ["wildlife", "water_wetlands"]),
    ("پارک ملی",              7, ["wildlife"]),
    ("منطقه حفاظت‌شده",       8, ["wildlife"]),
    ("ذخیره‌گاه زیست‌کره",    9, ["wildlife"]),
    ("بیوسفر",                8, ["wildlife"]),
    ("کانون آب و خاک",        6, ["wildlife", "forests"]),

    # ── آب/تالاب/دریا ─────────────────────────────────────────
    ("تالاب",                10, ["water_wetlands"]),
    ("دریاچه",                8, ["water_wetlands"]),
    ("رودخانه",               7, ["water_wetlands"]),
    ("خلیج فارس",             8, ["water_wetlands"]),
    ("دریای خزر",             9, ["water_wetlands"]),
    ("دریای عمان",            7, ["water_wetlands"]),
    ("آب‌های زیرزمینی",       8, ["water_wetlands"]),
    ("سفره آب زیرزمینی",      8, ["water_wetlands"]),
    ("بحران آب",              10, ["water_wetlands", "climate"]),
    ("کم‌آبی",               9, ["water_wetlands", "climate"]),
    ("خشکسالی",               9, ["water_wetlands", "climate"]),
    ("کاهش سطح آب",           8, ["water_wetlands"]),
    ("خشک شدن",               8, ["water_wetlands", "climate"]),
    ("برداشت آب",             7, ["water_wetlands"]),
    ("مصرف آب",               6, ["water_wetlands"]),
    ("تنش آبی",               9, ["water_wetlands", "climate"]),
    ("سد",                    6, ["water_wetlands"]),
    ("احداث سد",              7, ["water_wetlands"]),
    ("انتقال آب",             7, ["water_wetlands"]),
    ("آبیاری قطره‌ای",        6, ["water_wetlands", "sustainable"]),
    ("کانون‌های بحران آب",    9, ["water_wetlands", "climate"]),
    ("تالاب انزلی",           9, ["water_wetlands"]),
    ("هورالعظیم",             9, ["water_wetlands"]),
    ("هامون",                 9, ["water_wetlands"]),
    ("ارومیه",                9, ["water_wetlands"]),
    ("دریاچه ارومیه",        10, ["water_wetlands", "climate"]),
    ("بازیابی تالاب",         9, ["water_wetlands"]),
    ("احیای تالاب",           9, ["water_wetlands"]),
    ("رامسر",                 7, ["water_wetlands"]),
    ("کنوانسیون رامسر",       7, ["water_wetlands"]),
    ("پیامد سیل",             8, ["water_wetlands", "climate"]),
    ("مدیریت سیلاب",          7, ["water_wetlands", "climate"]),
    ("آبخیزداری",             7, ["water_wetlands", "forests"]),

    # ── تغییر اقلیم/بحران ────────────────────────────────────
    ("تغییر اقلیم",          10, ["climate"]),
    ("تغییر آب‌وهوا",        10, ["climate"]),
    ("گرمایش جهانی",         10, ["climate"]),
    ("گازهای گلخانه‌ای",     10, ["climate"]),
    ("دی‌اکسید کربن",         8, ["climate"]),
    ("CO2",                   8, ["climate"]),
    ("متان",                  8, ["climate"]),
    ("ردپای کربن",            8, ["climate"]),
    ("اثر گلخانه‌ای",         8, ["climate"]),
    ("بحران اقلیمی",         10, ["climate"]),
    ("اضطرار اقلیمی",        10, ["climate"]),
    ("سیل",                   8, ["climate", "water_wetlands"]),
    ("زلزله",                 6, ["climate"]),
    ("آتش‌سوزی جنگل",        10, ["climate", "forests"]),
    ("آتش‌سوزی",              7, ["climate", "forests"]),
    ("حریق",                  6, ["climate", "forests"]),
    ("موج گرما",              9, ["climate"]),
    ("گرمای بی‌سابقه",        9, ["climate"]),
    ("ریزش کوه",              6, ["climate"]),
    ("رانش زمین",             7, ["climate"]),
    ("طوفان",                 7, ["climate"]),
    ("توفان",                 6, ["climate"]),
    ("بارندگی شدید",          7, ["climate"]),
    ("ذوب یخچال",             9, ["climate"]),
    ("یخچال طبیعی",           8, ["climate"]),
    ("بیابان‌زایی",            9, ["climate", "forests"]),
    ("تخریب اراضی",           8, ["climate", "forests"]),
    ("اقلیم",                 6, ["climate"]),
    ("سازگاری با اقلیم",      8, ["climate"]),
    ("تاب‌آوری اقلیمی",       8, ["climate"]),
    ("COP",                   8, ["climate", "policy"]),
    ("پیمان پاریس",           8, ["climate", "policy"]),
    ("کربن‌خنثی",             8, ["climate", "sustainable"]),
    ("خنثی‌سازی کربن",        8, ["climate", "sustainable"]),
    ("تعهدات اقلیمی",         7, ["climate", "policy"]),

    # ── جنگل/مرتع/منابع طبیعی ────────────────────────────────
    ("جنگل",                  9, ["forests"]),
    ("جنگل‌زدایی",           10, ["forests"]),
    ("قطع درخت",             10, ["forests"]),
    ("بیشه",                  7, ["forests"]),
    ("مرتع",                  8, ["forests"]),
    ("تخریب مرتع",            9, ["forests"]),
    ("منابع طبیعی",           8, ["forests"]),
    ("جنگل‌های هیرکانی",      9, ["forests"]),
    ("جنگل ابری",             8, ["forests"]),
    ("جنگل‌کاری",             8, ["forests"]),
    ("درخت‌کاری",             7, ["forests"]),
    ("کاشت درخت",             6, ["forests"]),
    ("فرسایش خاک",            9, ["forests", "air_water_soil"]),
    ("حریم جنگل",             7, ["forests"]),
    ("تجاوز به جنگل",         8, ["forests"]),
    ("تخریب جنگل",            9, ["forests"]),
    ("ذغال‌گیری",             7, ["forests"]),
    ("مخروبه",                5, ["forests"]),
    ("کانون بحران خاک",       8, ["forests", "air_water_soil"]),

    # ── سیاست‌ها/قوانین/سازمان ───────────────────────────────
    ("سازمان محیط‌زیست",     10, ["policy"]),
    ("سازمان حفاظت محیط‌زیست",10,["policy"]),
    ("وزارت محیط‌زیست",       9, ["policy"]),
    ("قانون محیط‌زیست",        9, ["policy"]),
    ("قوانین زیست‌محیطی",     8, ["policy"]),
    ("ارزیابی زیست‌محیطی",    8, ["policy"]),
    ("ارزیابی اثرات محیطی",   8, ["policy"]),
    ("مجوز زیست‌محیطی",       7, ["policy"]),
    ("استانداردهای زیست‌محیطی",7,["policy"]),
    ("حقوق محیط‌زیست",        7, ["policy"]),
    ("جرایم زیست‌محیطی",      8, ["policy"]),
    ("جریمه زیست‌محیطی",      7, ["policy"]),
    ("پلیس محیط‌زیست",        8, ["policy"]),
    ("سازمان محیط زیست ملل",  8, ["policy"]),
    ("UNEP",                  7, ["policy"]),
    ("برنامه محیط‌زیست ملل",  7, ["policy"]),
    ("رئیس سازمان محیط‌زیست", 9, ["policy"]),
    ("بودجه محیط‌زیست",       7, ["policy"]),
    ("طرح محیط‌زیست",         7, ["policy"]),
    ("برنامه صیانت",          7, ["policy"]),
    ("شورای عالی محیط‌زیست",  8, ["policy"]),

    # ── توسعه پایدار/انرژی پاک ───────────────────────────────
    ("توسعه پایدار",          9, ["sustainable"]),
    ("انرژی تجدیدپذیر",      10, ["sustainable"]),
    ("انرژی خورشیدی",         9, ["sustainable"]),
    ("پنل خورشیدی",           8, ["sustainable"]),
    ("انرژی بادی",            9, ["sustainable"]),
    ("توربین بادی",            7, ["sustainable"]),
    ("انرژی پاک",             9, ["sustainable"]),
    ("انرژی سبز",             8, ["sustainable"]),
    ("اقتصاد سبز",            8, ["sustainable"]),
    ("اقتصاد چرخشی",         8, ["sustainable"]),
    ("بازیافت",               8, ["sustainable"]),
    ("بازیافت زباله",          8, ["sustainable"]),
    ("کاهش مصرف",             6, ["sustainable"]),
    ("ساختمان سبز",           7, ["sustainable"]),
    ("حمل‌ونقل پاک",          7, ["sustainable"]),
    ("خودرو برقی",            7, ["sustainable"]),
    ("هیدروژن سبز",           8, ["sustainable"]),
    ("اهداف توسعه پایدار",    7, ["sustainable", "policy"]),
    ("SDG",                   6, ["sustainable", "policy"]),
    ("مصرف انرژی",            5, ["sustainable"]),
    ("کارایی انرژی",          6, ["sustainable"]),
    ("گواهینامه سبز",         6, ["sustainable"]),
    ("استانداردهای سبز",      6, ["sustainable"]),
    ("محیط‌زیست",             6, ["policy"]),    # کلی
    ("اکولوژی",               6, ["wildlife"]),
    ("زیست‌بوم",              6, ["wildlife"]),
    ("طبیعت",                 4, ["wildlife"]),
    ("طبیعت‌گردی",            4, ["sustainable"]),
    ("اکوتوریسم",             6, ["sustainable"]),
    ("گردشگری پایدار",        5, ["sustainable"]),
]

# ═══════════════════════════════════════════════════════════════
# ۳) بلک‌لیست (کلماتی که خبر را رد می‌کنند)
# ═══════════════════════════════════════════════════════════════
BLACKLIST: list[str] = [
    # سیاسی
    "انتخابات", "مجلس", "دولت", "وزیر", "رئیس‌جمهور", "حزب",
    "نماینده مجلس", "اصلاح‌طلب", "اصولگرا", "رأی",
    # اقتصادی غیر مرتبط
    "بورس", "سهام", "بانک", "ارز", "دلار", "تورم", "مسکن",
    "خودرو سازی", "واردات", "صادرات", "تعرفه گمرکی",
    # ورزشی
    "فوتبال", "کشتی", "والیبال", "المپیک", "ورزشکار", "مسابقه",
    "لیگ برتر", "باشگاه ورزشی", "فدراسیون ورزش",
    # اجتماعی غیر مرتبط
    "ازدواج", "طلاق", "بازنشستگی", "آموزش‌وپرورش",
    "دانشگاه", "کنکور", "دانشجو", "مدرسه",
    # امنیتی/نظامی
    "سپاه", "ارتش", "نیروی دریایی", "موشک", "جنگ", "حمله نظامی",
    "تروریست", "تحریم", "برجام",
    # بهداشت غیر مرتبط
    "جراحی", "بیمارستان", "دارو", "واکسن",
]

# ═══════════════════════════════════════════════════════════════
# ۴) regex از پیش کامپایل‌شده برای سرعت
# ═══════════════════════════════════════════════════════════════
def _build_patterns(
    keywords: list[tuple[str, int, list[str]]]
) -> list[tuple[re.Pattern, int, list[str]]]:
    patterns = []
    for kw, weight, cats in keywords:
        if len(kw) <= 4:
            # مرز کلمه برای کلمات کوتاه (جلوگیری از false positive)
            pat = re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)")
        else:
            pat = re.compile(re.escape(kw))
        patterns.append((pat, weight, cats))
    return patterns

KEYWORD_PATTERNS = _build_patterns(WEIGHTED_KEYWORDS)

BLACKLIST_PATTERNS: list[re.Pattern] = [
    re.compile(re.escape(bl)) for bl in BLACKLIST
]


# ═══════════════════════════════════════════════════════════════
# ۵) تابع اصلی فیلتر
# ═══════════════════════════════════════════════════════════════
class NewsFilter:
    """فیلتر ۴ لایه برای اخبار محیط‌زیستی"""

    def filter_batch(
        self, items: list[RawNewsItem], known_uids: set[str]
    ) -> list[FilteredNewsItem]:
        """
        یک دسته خبر را فیلتر می‌کند.
        known_uids: مجموعه uid های قبلاً ذخیره‌شده (تکراری نباشند)
        """
        filtered: list[FilteredNewsItem] = []

        for item in items:
            result = self._process_item(item, known_uids)
            if result:
                filtered.append(result)

        logger.info(
            "🔍 فیلتر: %d ورودی → %d خبر محیط‌زیستی",
            len(items), len(filtered)
        )
        return filtered

    def _process_item(
        self, item: RawNewsItem, known_uids: set[str]
    ) -> Optional[FilteredNewsItem]:
        """یک خبر را از ۴ لایه رد می‌کند."""

        # لایه ۰: تکرار (قبل از هر چیز)
        if item.uid in known_uids:
            return None

        # لایه ۱: اعتبارسنجی فیلد
        if not self._validate_fields(item):
            return None

        # متن برای بررسی
        full_text = f"{item.title} {item.summary}"

        # لایه ۲: بلک‌لیست
        if self._is_blacklisted(full_text):
            return None

        # لایه ۳: امتیازدهی وزن‌دار
        score, matched_kws, category_scores = self._score(full_text)

        # آستانه بر اساس نوع فید
        threshold = (
            SCORE_THRESHOLD_DEDICATED
            if item.feed_dedicated
            else SCORE_THRESHOLD_GENERAL
        )
        if score < threshold:
            return None

        # لایه ۴: دسته‌بندی
        category = self._categorize(category_scores)

        # تشخیص بحران
        critical = score >= CRITICAL_SCORE_THRESHOLD or self._has_critical_phrase(
            full_text
        )

        return FilteredNewsItem(
            uid=item.uid,
            title=item.title,
            summary=item.summary,
            link=item.link,
            source=item.source,
            published_dt=item.published_dt,
            image_url=item.image_url,
            category=category,
            score=score,
            critical=critical,
            matched_keywords=matched_kws[:10],  # حداکثر ۱۰ کلمه کلیدی
            feed_dedicated=item.feed_dedicated,
            feed_priority=item.feed_priority,
        )

    @staticmethod
    def _validate_fields(item: RawNewsItem) -> bool:
        """لایه ۱: بررسی وجود فیلدهای ضروری"""
        if not item.title or len(item.title.strip()) < 5:
            return False
        if not item.link or not item.link.startswith("http"):
            return False
        # جلوگیری از خبرهای خیلی کوتاه
        if len(item.title) + len(item.summary) < 20:
            return False
        return True

    @staticmethod
    def _is_blacklisted(text: str) -> bool:
        """لایه ۲: بررسی بلک‌لیست"""
        for pat in BLACKLIST_PATTERNS:
            if pat.search(text):
                return True
        return False

    @staticmethod
    def _score(text: str) -> tuple[int, list[str], dict[str, int]]:
        """
        لایه ۳: امتیازدهی وزن‌دار
        خروجی: (امتیاز کل, کلمات مطابق, امتیاز هر دسته)
        """
        total_score = 0
        matched: list[str] = []
        category_scores: dict[str, int] = {c.id: 0 for c in CATEGORIES}

        for pat, weight, cats in KEYWORD_PATTERNS:
            if pat.search(text):
                total_score += weight
                matched.append(pat.pattern.replace("\\", ""))
                for cat in cats:
                    if cat in category_scores:
                        category_scores[cat] += weight

        return total_score, matched, category_scores

    @staticmethod
    def _categorize(category_scores: dict[str, int]) -> Category:
        """لایه ۴: انتخاب دسته با بالاترین امتیاز"""
        from src.config import CATEGORY_MAP, CATEGORIES
        if not any(category_scores.values()):
            return CATEGORIES[-1]  # سیاست‌ها به عنوان پیش‌فرض
        best_cat_id = max(category_scores, key=lambda k: category_scores[k])
        return CATEGORY_MAP.get(best_cat_id, CATEGORIES[-1])

    @staticmethod
    def _has_critical_phrase(text: str) -> bool:
        """تشخیص عبارات بحرانی صریح"""
        critical_phrases = [
            "بحران", "فاجعه", "فوری", "اضطرار", "هشدار قرمز",
            "خطر جدی", "وضعیت بحرانی", "آلوده‌ترین",
            "انقراض قطعی", "آتش‌سوزی گسترده", "نشت گاز",
            "آلودگی شدید", "مرگ ماهیان", "تلفات حیات وحش",
            "بدترین", "بی‌سابقه", "فوریت",
        ]
        for phrase in critical_phrases:
            if phrase in text:
                return True
        return False


# تابع سطح بالا برای استفاده در main.py
def filter_news(
    items: list[RawNewsItem], known_uids: set[str]
) -> list[FilteredNewsItem]:
    return NewsFilter().filter_batch(items, known_uids)
