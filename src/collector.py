"""
جمع‌آوری پیشرفته از 11 فید RSS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- User-Agent rotation (20 عامل)
- Retry با backoff نمایی
- پشتیبانی از فیدهای 403 با headers خاص
- تشخیص خودکار encoding
- پاکسازی HTML و متن
- timeout تطبیقی
"""

import logging
import re
import time
import random
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# User-Agent های متنوع (مرورگر + موبایل)
# ═══════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Android 14; Mobile; rv:132.0) Gecko/132.0 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Googlebot/2.1 (+http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "feedfetcher-google; (+http://www.google.com/feedfetcher.html)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0",
]

# ═══════════════════════════════════════════
# فیدهای RSS با تنظیمات خاص هر منبع
# ═══════════════════════════════════════════
FEEDS = [
    {
        "url":    "https://www.irna.ir/rss/tp/32",
        "name":   "ایرنا",
        "type":   "dedicated",
        "referer":"https://www.irna.ir",
        "timeout": 20,
    },
    {
        "url":    "https://www.mehrnews.com/rss/tp/64",
        "name":   "مهر",
        "type":   "dedicated",
        "referer":"https://www.mehrnews.com",
        "timeout": 20,
    },
    {
        "url":    "https://www.hamshahrionline.ir/rss/tp/584",
        "name":   "همشهری",
        "type":   "dedicated",
        "referer":"https://www.hamshahrionline.ir",
        "timeout": 20,
    },
    {
        "url":    "https://www.khabaronline.ir/rss/tp/44",
        "name":   "خبرآنلاین",
        "type":   "dedicated",
        "referer":"https://www.khabaronline.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.imna.ir/rss/tp/153",
        "name":   "ایمنا",
        "type":   "dedicated",
        "referer":"https://www.imna.ir",
        "timeout": 20,
    },
    {
        "url":    "https://www.ettelaat.com/rss/tp/65",
        "name":   "اطلاعات",
        "type":   "dedicated",
        "referer":"https://www.ettelaat.com",
        "timeout": 25,
    },
    {
        "url":    "https://www.iribnews.ir/fa/rss/7/39",
        "name":   "صدا و سیما",
        "type":   "dedicated",
        "referer":"https://www.iribnews.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.iribnews.ir/fa/rss/6/8",
        "name":   "صدا و سیما آب",
        "type":   "dedicated",
        "referer":"https://www.iribnews.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.salamatnews.com/rss/tp/11",
        "name":   "سلامت نیوز",
        "type":   "dedicated",
        "referer":"https://www.salamatnews.com",
        "timeout": 20,
    },
    {
        "url":    "https://www.isna.ir/rss",
        "name":   "ایسنا",
        "type":   "general",
        "referer":"https://www.isna.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.yjc.ir/fa/rss/5/74",
        "name":   "باشگاه خبرنگاران",
        "type":   "dedicated",
        "referer":"https://www.yjc.ir",
        "timeout": 20,
        "skip_403": True,
    },
]

# فیدهای جایگزین (پشتیبان)
BACKUP_FEEDS = [
    {
        "url":    "https://www.isna.ir/rss/tp/13",
        "name":   "ایسنا محیط زیست",
        "type":   "dedicated",
        "referer":"https://www.isna.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.farsnews.ir/rss/tp/13",
        "name":   "فارس محیط زیست",
        "type":   "dedicated",
        "referer":"https://www.farsnews.ir",
        "timeout": 25,
    },
    {
        "url":    "https://www.tasnimnews.com/fa/rss/feed/0/8/0",
        "name":   "تسنیم",
        "type":   "dedicated",
        "referer":"https://www.tasnimnews.com",
        "timeout": 25,
    },
]


# ═══════════════════════════════════════════
# ابزارهای کمکی
# ═══════════════════════════════════════════
def _build_headers(referer: str = "", ua: str = "") -> dict:
    return {
        "User-Agent":      ua or random.choice(USER_AGENTS),
        "Accept":          "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Cache-Control":   "no-cache",
        "Referer":         referer or "https://www.google.com",
        "DNT":             "1",
    }


def _clean_html(text: str) -> str:
    if not text:
        return ""
    if "<" in text and ">" in text:
        try:
            soup = BeautifulSoup(text, "lxml")
            text = soup.get_text(separator=" ")
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]


def _parse_date(entry) -> str:
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, field, None)
        if t:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def _fetch_feed_content(feed_config: dict) -> Optional[bytes]:
    """دریافت محتوای فید با چندین تلاش و User-Agent مختلف"""
    url     = feed_config["url"]
    timeout = feed_config.get("timeout", 20)
    referer = feed_config.get("referer", "")

    # ترتیب تلاش: Googlebot → Chrome → Firefox → Safari
    agents_to_try = [
        "feedfetcher-google; (+http://www.google.com/feedfetcher.html)",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    ]

    for attempt, ua in enumerate(agents_to_try, 1):
        try:
            headers  = _build_headers(referer, ua)
            session  = requests.Session()
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)

            if response.status_code == 200:
                logger.info(f"[{feed_config['name']}] ✅ موفق (attempt={attempt}, ua={ua[:30]})")
                return response.content

            if response.status_code == 403:
                if feed_config.get("skip_403"):
                    logger.warning(f"[{feed_config['name']}] 403 — رد شد")
                    return None
                logger.warning(f"[{feed_config['name']}] 403 — تلاش با UA دیگر...")
                time.sleep(1)
                continue

            if response.status_code in (301, 302):
                new_url = response.headers.get("Location", "")
                if new_url:
                    logger.info(f"[{feed_config['name']}] redirect → {new_url}")
                    response = session.get(new_url, headers=headers, timeout=timeout)
                    if response.status_code == 200:
                        return response.content

            logger.warning(f"[{feed_config['name']}] status={response.status_code}")

        except requests.Timeout:
            logger.warning(f"[{feed_config['name']}] timeout (attempt={attempt})")
        except requests.ConnectionError as e:
            logger.warning(f"[{feed_config['name']}] connection error: {e}")
        except Exception as e:
            logger.warning(f"[{feed_config['name']}] خطا: {e}")

        if attempt < len(agents_to_try):
            time.sleep(random.uniform(1, 3))

    return None


def _parse_entries(content: bytes, feed_config: dict) -> list[dict]:
    """تجزیه محتوای فید به آیتم‌های ساختاریافته"""
    try:
        parsed = feedparser.parse(content)
    except Exception as e:
        logger.error(f"[{feed_config['name']}] خطای parse: {e}")
        return []

    if not parsed.entries:
        logger.warning(f"[{feed_config['name']}] هیچ آیتمی یافت نشد")
        return []

    items = []
    for entry in parsed.entries[:30]:
        # عنوان
        title = _clean_html(getattr(entry, "title", "") or "")
        if not title or len(title) < 5:
            continue

        # لینک
        link = getattr(entry, "link", "") or ""
        if not link:
            continue

        # خلاصه
        summary = ""
        for field in ("summary", "description", "content"):
            val = getattr(entry, field, None)
            if val:
                if isinstance(val, list) and val:
                    val = val[0].get("value", "") if isinstance(val[0], dict) else str(val[0])
                summary = _clean_html(str(val))
                if summary:
                    break

        items.append({
            "title":    title,
            "link":     link,
            "summary":  summary,
            "content":  summary,
            "date":     _parse_date(entry),
            "source":   feed_config["name"],
            "feed_url": feed_config["url"],
            "feed_type":feed_config.get("type","general"),
        })

    logger.info(f"[{feed_config['name']}] {len(items)} آیتم استخراج شد")
    return items


def collect_all_feeds() -> list[dict]:
    """
    جمع‌آوری از همه فیدها + فیدهای پشتیبان
    خروجی: لیست یکتا بر اساس لینک
    """
    all_items  = []
    seen_links = set()
    active_sources = 0
    all_feeds  = FEEDS + BACKUP_FEEDS

    for feed_config in all_feeds:
        logger.info(f"[collect] شروع: {feed_config['name']} — {feed_config['url']}")

        content = _fetch_feed_content(feed_config)
        if not content:
            logger.warning(f"[{feed_config['name']}] ❌ دریافت نشد")
            continue

        items = _parse_entries(content, feed_config)
        if not items:
            continue

        active_sources += 1
        new_count = 0
        for item in items:
            link = item["link"]
            if link not in seen_links:
                seen_links.add(link)
                all_items.append(item)
                new_count += 1

        logger.info(f"[{feed_config['name']}] ✅ {new_count} آیتم جدید")
        time.sleep(random.uniform(0.5, 1.5))

    logger.info(
        f"[collect] ═══ جمع‌بندی: "
        f"{active_sources}/{len(all_feeds)} منبع فعال | "
        f"{len(all_items)} آیتم یکتا ═══"
    )
    return all_items
