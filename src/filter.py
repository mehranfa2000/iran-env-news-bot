# ============================================================
#  src/filter.py — فیلتر ۳ لایه محیط‌زیستی
#  لایه ۱: کلیدواژه | لایه ۲: امتیازدهی | لایه ۳: سیاه‌برگ
# ============================================================

from src.keywords import ALL_KEYWORDS, BLACKLIST, CATEGORIES, get_category
from src.config   import (
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
    TITLE_SCORE_WEIGHT,
    BODY_SCORE_WEIGHT,
)


def _score(article: dict) -> int:
    """محاسبه امتیاز محیط‌زیستی یک خبر"""
    title   = article.get("title",   "").lower()
    summary = article.get("summary", "").lower()
    score   = 0
    for kw in ALL_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title:
            score += TITLE_SCORE_WEIGHT
        if kw_lower in summary:
            score += BODY_SCORE_WEIGHT
    return score


def _has_blacklist(article: dict) -> bool:
    """آیا خبر شامل کلیدواژه سیاه‌برگ است؟"""
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()
    return any(bl.lower() in text for bl in BLACKLIST)


def _get_threshold(article: dict) -> int:
    """آستانه امتیاز بر اساس نوع فید"""
    if article.get("dedicated", False):
        return SCORE_THRESHOLD_DEDICATED
    return SCORE_THRESHOLD_GENERAL


def filter_news(articles: list) -> list:
    """
    فیلتر ۳ لایه اخبار محیط‌زیستی

    لایه ۱: حداقل یک کلیدواژه در عنوان یا متن
    لایه ۲: امتیاز کافی (عنوان=۳ | متن=۱)
    لایه ۳: بدون کلیدواژه سیاه‌برگ

    Returns:
        لیست اخبار فیلترشده با دسته‌بندی اضافه‌شده
    """
    passed = []

    for article in articles:
        title   = article.get("title",   "").lower()
        summary = article.get("summary", "").lower()
        full    = title + " " + summary

        # لایه ۱: حداقل یک کلیدواژه
        has_keyword = any(kw.lower() in full for kw in ALL_KEYWORDS)
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

        # افزودن دسته‌بندی و امتیاز
        cat_name, cat_emoji = get_category(full)
        article["category"]       = cat_name
        article["category_emoji"] = cat_emoji
        article["score"]          = score

        passed.append(article)

    return passed
