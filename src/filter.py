# ============================================================
#  src/filter.py — فیلتر ۳ لایه + بررسی مرز کلمه
#  رفع باگ: «دام» در «اقدامات» دیگر match نمی‌شود
# ============================================================

import re
from src.keywords import ALL_KEYWORDS, BLACKLIST, SHORT_KEYWORDS, get_category
from src.config   import (
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
    TITLE_SCORE_WEIGHT,
    BODY_SCORE_WEIGHT,
)


def _keyword_in_text(keyword: str, text: str) -> bool:
    """
    بررسی وجود کلیدواژه در متن
    برای کلیدواژه‌های کوتاه (≤۴ حرف): بررسی مرز کلمه
    برای کلیدواژه‌های بلند: جستجوی ساده زیررشته‌ای
    """
    if not keyword or not text:
        return False

    kw_lower = keyword.lower()

    if keyword in SHORT_KEYWORDS:
        # بررسی مرز کلمه: کلیدواژه باید به عنوان کلمه مستقل باشد
        # از فاصله، نیم‌فاصله، ابتدا/انتهای متن، علائم نگارشی
        pattern = r'(?:^|[\s\u200c\u200d.,;:!?،؛/\-(){}\[\]])'
        pattern += re.escape(kw_lower)
        pattern += r'(?:$|[\s\u200c\u200d.,;:!?،؛/\-(){}\[\]])'
        return bool(re.search(pattern, text))
    else:
        return kw_lower in text


def _score(article: dict) -> int:
    """محاسبه امتیاز با بررسی مرز کلمه"""
    title   = article.get("title",   "").lower()
    summary = article.get("summary", "").lower()
    score   = 0
    for kw in ALL_KEYWORDS:
        if _keyword_in_text(kw, title):
            score += TITLE_SCORE_WEIGHT
        if _keyword_in_text(kw, summary):
            score += BODY_SCORE_WEIGHT
    return score


def _has_blacklist(article: dict) -> bool:
    """آیا خبر شامل کلیدواژه سیاه‌برگ است؟"""
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()
    return any(bl.lower() in text for bl in BLACKLIST)


def _get_threshold(article: dict) -> int:
    if article.get("dedicated", False):
        return SCORE_THRESHOLD_DEDICATED
    return SCORE_THRESHOLD_GENERAL


def filter_news(articles: list) -> list:
    """فیلتر ۳ لایه اخبار محیط‌زیستی"""
    passed = []

    for article in articles:
        title   = article.get("title",   "").lower()
        summary = article.get("summary", "").lower()
        full    = title + " " + summary

        # لایه ۱: حداقل یک کلیدواژه (با بررسی مرز)
        has_keyword = any(_keyword_in_text(kw, full) for kw in ALL_KEYWORDS)
        if not has_keyword:
            continue

        # لایه ۲: امتیاز کافی
        score     = _score(article)
        threshold = _get_threshold(article)
        if score < threshold:
            continue

        # لایه ۳: سیاه‌برگ
        if _has_blacklist(article):
            continue

        # افزودن دسته‌بندی
        cat_name, cat_emoji = get_category(full)
        article["category"]       = cat_name
        article["category_emoji"] = cat_emoji
        article["score"]          = score

        passed.append(article)

    return passed
