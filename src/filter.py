"""
filter.py — فیلتر ۴ لایه‌ای اخبار محیط‌زیست
نسخه: 4.2.0

تغییرات v4.2:
- word boundary فارسی برای کلمات ≤ ۴ کاراکتر
  (جلوگیری از «دام» در «اقدامات»)
- Regex pattern cache برای کارایی
- Blacklist با word boundary (نه substring ساده)
- دسته‌بندی بر اساس وزن کلمات کلیدی دسته
- آمار کامل فیلتر در هر ران
- API منسجم: filter_articles() → list[(article, FilterResult)]
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    KEYWORDS, BLACKLIST, CATEGORIES, CATEGORY_MAP,
    SCORE_THRESHOLD_DEDICATED, SCORE_THRESHOLD_GENERAL,
    CRITICAL_SCORE_THRESHOLD,
)

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# مدل نتیجه فیلتر
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class FilterResult:
    """نتیجه فیلتر یک خبر."""
    passed:           bool
    score:            int
    category:         str
    critical:         bool
    reject_reason:    Optional[str]    = None
    matched_keywords: list[str]        = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Word Boundary فارسی
# ══════════════════════════════════════════════════════════════════════════════
"""
چالش: زبان فارسی کاراکتر جداکننده کلمه (word boundary) ندارد.
\b در Python regex برای یونیکد کار نمی‌کند.

راه‌حل:
- کلمات ≤ ۴ کاراکتر: بررسی مرز با lookaround
  مرزها: فاصله، نیم‌فاصله (U+200C)، علائم نگارشی فارسی/لاتین، ابتدا/انتهای رشته
- کلمات > ۴ کاراکتر: substring ساده (کافی است)
  مثال: «محیط‌زیست» در متن هر کجا باشد مرتبط است

مثال‌های مهم:
  «آب» (۲ کاراکتر) در «آبخوان» → نباید match کند
  «آب» در «آب زیرزمینی» → باید match کند
  «دام» (۳ کاراکتر) در «اقدامات» → نباید match کند
  «دام» در «دام‌های غیرمجاز» → باید match کند
"""

# کاراکترهای مرزی (جداکننده‌ها)
_SEPARATORS = (
    r'\s'          # فاصله، tab، newline
    r'|\u200c'     # نیم‌فاصله فارسی (ZWNJ)
    r'|\u200b'     # Zero-width space
    r'|[،؛؟!«»\(\)\[\]\{\}\.\,\:\;\-\_\/\\]'  # علائم نگارشی
)

# Pattern: (ابتدای رشته | separator) + keyword + (انتهای رشته | separator)
_BOUNDARY_TMPL = r'(?:(?:^|(?<=[{seps}])){kw}(?=$|[{seps}]))'

# جایگزین ساده‌تر که در Python regex کار می‌کند
def _make_boundary_pattern(keyword: str) -> re.Pattern:
    """
    Pattern با مرز برای کلمات کوتاه (≤ ۴ کاراکتر).

    استفاده از lookahead/lookbehind با کلاس کاراکتری.
    """
    esc = re.escape(keyword)
    # مرز: قبل از keyword نباید حرف/عدد فارسی/عربی/لاتین باشد
    # بعد از keyword هم نباید حرف/عدد باشد
    pattern = (
        r'(?<![^\W\s])'    # lookbehind: قبل از keyword جدا شده
        + esc +
        r'(?![^\W\s])'     # lookahead: بعد از keyword جدا شده
    )
    # روش مطمئن‌تر برای یونیکد فارسی:
    fa_chars = r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFFa-zA-Z0-9]'
    pattern = (
        r'(?<!' + fa_chars[1:-1] + r')' +   # قبل: نباید حرف باشد
        esc +
        r'(?!' + fa_chars[1:-1] + r')'      # بعد: نباید حرف باشد
    )
    return re.compile(pattern, re.UNICODE | re.MULTILINE)


# Cache برای patterns (محاسبه یک‌بار، استفاده چندباره)
_pattern_cache: dict[str, re.Pattern] = {}


def _get_pattern(keyword: str) -> re.Pattern:
    if keyword not in _pattern_cache:
        _pattern_cache[keyword] = _make_boundary_pattern(keyword)
    return _pattern_cache[keyword]


def _keyword_matches(keyword: str, text: str) -> bool:
    """
    بررسی وجود کلمه کلیدی در متن.

    - ≤ ۴ کاراکتر: بررسی مرز (جلوگیری از false positive)
    - > ۴ کاراکتر: substring ساده (سریع‌تر، کافی است)
    """
    if len(keyword) <= 4:
        return bool(_get_pattern(keyword).search(text))
    return keyword in text


def _blacklist_matches(keyword: str, text: str) -> bool:
    """
    بررسی کلمات بلک‌لیست.
    همیشه با word boundary بررسی می‌کند (حتی کلمات بلند).
    """
    if len(keyword) <= 4:
        return bool(_get_pattern(keyword).search(text))
    # برای بلک‌لیست: کل عبارت را با مرز بررسی کن
    if keyword not in _pattern_cache:
        _pattern_cache[keyword] = _make_boundary_pattern(keyword)
    return bool(_pattern_cache[keyword].search(text))


# ══════════════════════════════════════════════════════════════════════════════
# دسته‌بندی
# ══════════════════════════════════════════════════════════════════════════════
def _categorize(text: str) -> str:
    """
    بهترین دسته‌بندی را بر اساس وزن کلمات کلیدی آن دسته تعیین می‌کند.

    برای هر دسته: مجموع وزن کلمات کلیدی دسته که در متن هستند.
    دسته‌ای که بیشترین مجموع وزن را داشت → انتخاب می‌شود.
    اگر هیچ‌کدام → 'policy' (پیش‌فرض)
    """
    best_cat   = "policy"
    best_score = 0

    for cat_cfg in CATEGORIES:
        cat_score = 0
        for kw in cat_cfg.keywords:
            if _keyword_matches(kw, text):
                # وزن از جدول اصلی (اگر وجود داشت)؛ وگرنه ۱
                cat_score += KEYWORDS.get(kw, 1)
        if cat_score > best_score:
            best_score = cat_score
            best_cat   = cat_cfg.key

    return best_cat


# ══════════════════════════════════════════════════════════════════════════════
# فیلتر یک خبر
# ══════════════════════════════════════════════════════════════════════════════
def filter_article(
    title:         str,
    summary:       str,
    source:        str,
    dedicated:     bool,
    uid:           str,
    existing_uids: set[str],
) -> FilterResult:
    """
    فیلتر ۴ لایه‌ای یک خبر.

    لایه ۱: اعتبارسنجی فیلدها
    لایه ۲: تکراری بودن (uid در existing_uids)
    لایه ۳: بلک‌لیست (رد فوری)
    لایه ۴: امتیازدهی وزن‌دار + آستانه + دسته‌بندی
    """
    # ── لایه ۱: اعتبارسنجی ────────────────────────────────────────────────────
    title   = (title   or "").strip()
    summary = (summary or "").strip()

    if not title or len(title) < 5:
        return FilterResult(False, 0, "unknown", False, "عنوان ناقص")

    full_text = f"{title} {summary}".strip()

    # ── لایه ۲: تکراری ────────────────────────────────────────────────────────
    if uid in existing_uids:
        return FilterResult(False, 0, "duplicate", False, "تکراری")

    # ── لایه ۳: بلک‌لیست ──────────────────────────────────────────────────────
    for bad_word in BLACKLIST:
        if _blacklist_matches(bad_word, full_text):
            return FilterResult(
                False, 0, "blacklisted", False,
                f"بلک‌لیست: {bad_word}",
            )

    # ── لایه ۴: امتیازدهی ─────────────────────────────────────────────────────
    score:   int        = 0
    matched: list[str]  = []

    for keyword, weight in KEYWORDS.items():
        if _keyword_matches(keyword, full_text):
            score   += weight
            matched.append(keyword)

    # بافر ۳۰٪ برای منابع اختصاصی
    if dedicated:
        score = int(score * 1.3)

    # آستانه قبولی
    threshold = (
        SCORE_THRESHOLD_DEDICATED if dedicated
        else SCORE_THRESHOLD_GENERAL
    )
    if score < threshold:
        return FilterResult(
            False, score, "below_threshold", False,
            f"امتیاز {score} < آستانه {threshold}",
            matched,
        )

    # ── دسته‌بندی و flag بحرانی ───────────────────────────────────────────────
    category = _categorize(full_text)
    critical = score >= CRITICAL_SCORE_THRESHOLD

    if critical:
        log.info(
            f"🚨 بحرانی (امتیاز={score}): {title[:50]} | "
            f"دسته={category}"
        )

    return FilterResult(
        passed=True,
        score=score,
        category=category,
        critical=critical,
        matched_keywords=matched,
    )


# ══════════════════════════════════════════════════════════════════════════════
# فیلتر دسته‌ای (تابع اصلی برای main.py)
# ══════════════════════════════════════════════════════════════════════════════
def filter_articles(
    raw_articles,          # list[RawArticle]
    existing_uids: set[str],
) -> list[tuple]:           # list[tuple[RawArticle, FilterResult]]
    """
    همه RawArticle ها را فیلتر می‌کند.

    Returns:
        لیست (article, result) برای آیتم‌هایی که passed=True
        مرتب‌شده بر اساس score (بالاتر اول)
    """
    passed_pairs: list[tuple] = []

    # آمار برای logging
    stats = {
        "total":               0,
        "passed":              0,
        "rejected_duplicate":  0,
        "rejected_blacklist":  0,
        "rejected_score":      0,
        "rejected_validation": 0,
    }

    for article in raw_articles:
        stats["total"] += 1

        result = filter_article(
            title=article.title,
            summary=article.summary,
            source=article.source,
            dedicated=article.dedicated,
            uid=article.uid,
            existing_uids=existing_uids,
        )

        if result.passed:
            passed_pairs.append((article, result))
            stats["passed"] += 1
        else:
            reason = result.reject_reason or ""
            if "تکراری"    in reason: stats["rejected_duplicate"]  += 1
            elif "بلک‌لیست" in reason: stats["rejected_blacklist"]  += 1
            elif "ناقص"    in reason: stats["rejected_validation"] += 1
            else:                       stats["rejected_score"]      += 1

    # مرتب‌سازی: بحرانی‌ها اول، بعد بر اساس score نزولی
    passed_pairs.sort(
        key=lambda x: (x[1].critical, x[1].score),
        reverse=True,
    )

    log.info(
        f"📊 فیلتر: "
        f"کل={stats['total']} | "
        f"✅ قبول={stats['passed']} | "
        f"🔁 تکراری={stats['rejected_duplicate']} | "
        f"🚫 بلک‌لیست={stats['rejected_blacklist']} | "
        f"📉 امتیاز={stats['rejected_score']} | "
        f"⚠️  ناقص={stats['rejected_validation']}"
    )

    return passed_pairs
