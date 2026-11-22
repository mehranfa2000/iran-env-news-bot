import re
import logging
from src.keywords import (
    KEYWORDS, CATEGORIES, BLACKLIST,
    CRITICAL_KEYWORDS, SHORT_KEYWORDS,
)
from src.config import (
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
    TITLE_SCORE_WEIGHT,
    BODY_SCORE_WEIGHT,
)

logger = logging.getLogger(__name__)

# فیدهای اختصاصی محیط‌زیست (آستانه امتیاز پایین‌تر)
DEDICATED_FEEDS = {
    "irna.ir/rss/tp/32",
    "mehrnews.com/rss/tp/64",
    "hamshahrionline.ir/rss/tp/584",
    "khabaronline.ir/rss/tp/44",
    "imna.ir/rss/tp/153",
    "yjc.ir/fa/rss/5/74",
    "ettelaat.com/rss/tp/65",
    "iribnews.ir/fa/rss/7/39",
    "iribnews.ir/fa/rss/6/8",
    "salamatnews.com/rss/tp/11",
}


def _is_dedicated(url: str) -> bool:
    """بررسی اینکه فید اختصاصی است یا عمومی"""
    return any(feed in url for feed in DEDICATED_FEEDS)


def _keyword_in_text(keyword: str, text: str) -> bool:
    """
    بررسی وجود کلمه کلیدی در متن.
    برای کلمات کوتاه (≤4 کاراکتر): بررسی مرز کلمه
    برای کلمات بلند: بررسی ساده زیررشته
    """
    if keyword in SHORT_KEYWORDS:
        # مرز کلمه برای فارسی: فاصله، ابتدا/انتهای رشته، نشانه‌گذاری
        pattern = r'(?<![^\s،؛،.!?])' + re.escape(keyword) + r'(?![^\s،؛،.!?])'
        return bool(re.search(pattern, text))
    return keyword in text


def _has_blacklist(text: str) -> bool:
    """آیا متن شامل موارد لیست سیاه است؟"""
    return any(term in text for term in BLACKLIST)


def _calc_score(title: str, body: str) -> int:
    """محاسبه امتیاز کلمات کلیدی"""
    score = 0
    for kw in KEYWORDS:
        in_title = _keyword_in_text(kw, title)
        in_body  = _keyword_in_text(kw, body)
        score += (TITLE_SCORE_WEIGHT if in_title else 0)
        score += (BODY_SCORE_WEIGHT  if in_body  else 0)
    return score


def get_category(title: str, body: str) -> str:
    """تشخیص دسته‌بندی خبر"""
    text = title + " " + body
    best_cat   = "🏛️ سیاست‌ها، قوانین و سازمان محیط زیست"
    best_score = 0
    for cat, keywords in CATEGORIES.items():
        s = sum(1 for kw in keywords if kw in text)
        if s > best_score:
            best_score = s
            best_cat   = cat
    return best_cat


def is_critical(title: str, body: str) -> bool:
    """
    آیا خبر بحرانی است و باید به AI فرستاده شود؟
    معیار: داشتن حداقل یک کلمه بحرانی در عنوان یا بدنه
    """
    text = title + " " + body
    return any(kw in text for kw in CRITICAL_KEYWORDS)


def filter_news(items: list[dict], feed_url: str = "") -> list[dict]:
    """
    فیلتر سه‌لایه:
    1) بررسی لیست سیاه
    2) محاسبه امتیاز کلمات کلیدی
    3) اضافه کردن دسته‌بندی و پرچم بحرانی
    """
    dedicated = _is_dedicated(feed_url)
    threshold = SCORE_THRESHOLD_DEDICATED if dedicated else SCORE_THRESHOLD_GENERAL
    result    = []

    for item in items:
        title = item.get("title", "")
        body  = item.get("summary", "") + " " + item.get("content", "")

        # لایه ۱: لیست سیاه
        if _has_blacklist(title) or _has_blacklist(body):
            logger.debug(f"[blacklist] {title[:50]}")
            continue

        # لایه ۲: امتیازدهی
        score = _calc_score(title, body)
        if score < threshold:
            logger.debug(f"[low-score={score}] {title[:50]}")
            continue

        # لایه ۳: دسته‌بندی و پرچم بحرانی
        item["category"] = get_category(title, body)
        item["score"]    = score
        item["critical"] = is_critical(title, body)
        result.append(item)
        logger.info(f"[pass score={score} critical={item['critical']}] {title[:60]}")

    return result
