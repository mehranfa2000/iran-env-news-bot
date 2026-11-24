"""
collector.py — v4.0
جمع‌آوری موازی خبرها از ۱۴ فید RSS
قابلیت جدید: استخراج تصویر از خبر (enclosure / media:content / og:image)
"""

from __future__ import annotations
import hashlib
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from src.config import (
    FEEDS,
    FeedConfig,
    COLLECTOR_MAX_WORKERS,
    COLLECTOR_TIMEOUT,
    COLLECTOR_MAX_RETRIES,
    FEED_MAX_ENTRIES,
)

logger = logging.getLogger("collector")

# ═══════════════════════════════════════════════════════════════
# ۱) ساختار داده خبر خام
# ═══════════════════════════════════════════════════════════════
@dataclass
class RawNewsItem:
    uid: str                        # شناسه یکتا (hash لینک)
    title: str
    summary: str
    link: str
    source: str
    published_dt: datetime          # زمان انتشار (UTC)
    image_url: Optional[str]        = None
    feed_dedicated: bool            = True
    feed_priority: int              = 1
    raw_tags: list[str]             = field(default_factory=list)
    fetch_method: str               = "unknown"

    @staticmethod
    def make_uid(link: str) -> str:
        return hashlib.sha256(link.strip().encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
# ۲) User-Agent های مختلف برای bypass
# ═══════════════════════════════════════════════════════════════
USER_AGENTS: list[str] = [
    # Googlebot — بیشترین موفقیت
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    # feedfetcher
    "feedfetcher-google; (+http://www.google.com/feedfetcher.html)",
    # Chrome 131
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/131.0.0.0 Safari/537.36"),
    # Firefox 132
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
     "Gecko/20100101 Firefox/132.0"),
    # Safari 18
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/18.0 Safari/605.1.15"),
    # RSS Reader
    "Feedly/1.0 (+http://www.feedly.com/fetcher.html)",
]

# ═══════════════════════════════════════════════════════════════
# ۳) کلاس AdaptiveFetcher — دریافت هوشمند RSS
# ═══════════════════════════════════════════════════════════════
class AdaptiveFetcher:
    """
    دریافت فید RSS با چندین استراتژی موازی + fallback.
    برای هر فید، تا COLLECTOR_MAX_RETRIES بار تلاش می‌کند.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or self._make_session()

    @staticmethod
    def _make_session() -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        return s

    def fetch(self, feed: FeedConfig) -> list[RawNewsItem]:
        """
        یک فید را دریافت و parse می‌کند.
        در صورت خطا، با UA متفاوت تلاش مجدد می‌کند.
        """
        last_error: Optional[Exception] = None

        # ترتیب تلاش‌ها: http request → feedparser direct
        strategies = [
            ("http_request", lambda ua: self._fetch_via_requests(feed.url, ua)),
            ("feedparser_direct", lambda ua: self._fetch_via_feedparser(feed.url, ua)),
        ]

        for attempt, (method, fetch_fn) in enumerate(strategies):
            ua = random.choice(USER_AGENTS)
            try:
                items = fetch_fn(ua)
                if items:
                    logger.info("✅ [%s] %d خبر | روش: %s", feed.name, len(items), method)
                    for item in items:
                        item.fetch_method = method
                        item.feed_dedicated = feed.dedicated
                        item.feed_priority = feed.priority
                        item.source = feed.name
                    return items
            except Exception as exc:
                last_error = exc
                logger.debug("⚠️ [%s] تلاش %d شکست خورد: %s", feed.name, attempt + 1, exc)
                time.sleep(1.5)

        if feed.skip_on_error:
            logger.warning("⏭️ [%s] رد شد (skip_on_error=True)", feed.name)
            return []

        logger.error("❌ [%s] همه روش‌ها شکست خوردند: %s", feed.name, last_error)
        return []

    def _fetch_via_requests(self, url: str, ua: str) -> list[RawNewsItem]:
        """دریافت محتوا با requests و parse با feedparser"""
        resp = self.session.get(
            url,
            headers={"User-Agent": ua},
            timeout=COLLECTOR_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        content = resp.content
        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"feedparser bozo: {parsed.bozo_exception}")
        return self._parse_entries(parsed, url)

    def _fetch_via_feedparser(self, url: str, ua: str) -> list[RawNewsItem]:
        """دریافت مستقیم با feedparser"""
        parsed = feedparser.parse(
            url,
            agent=ua,
            request_headers={"Accept": "application/rss+xml, */*"},
        )
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"feedparser bozo: {parsed.bozo_exception}")
        return self._parse_entries(parsed, url)

    def _parse_entries(
        self, parsed: feedparser.FeedParserDict, base_url: str
    ) -> list[RawNewsItem]:
        """تبدیل entries فید به RawNewsItem"""
        items: list[RawNewsItem] = []
        entries = parsed.entries[:FEED_MAX_ENTRIES]

        for entry in entries:
            try:
                item = self._entry_to_item(entry, base_url)
                if item:
                    items.append(item)
            except Exception as exc:
                logger.debug("خطا در parse entry: %s", exc)

        return items

    def _entry_to_item(
        self, entry: feedparser.util.FeedParserDict, base_url: str
    ) -> Optional[RawNewsItem]:
        """یک entry فید را به RawNewsItem تبدیل می‌کند."""
        # عنوان
        title = self._clean_text(getattr(entry, "title", "") or "")
        if not title:
            return None

        # لینک
        link = (getattr(entry, "link", "") or "").strip()
        if not link:
            return None
        link = self._normalize_url(link, base_url)

        # خلاصه
        summary_raw = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        summary = self._clean_text(summary_raw, strip_html=True)

        # زمان انتشار
        published_dt = self._parse_date(entry)

        # تصویر
        image_url = self._extract_image(entry, summary_raw)

        # برچسب‌ها
        tags: list[str] = []
        for tag in getattr(entry, "tags", []):
            term = getattr(tag, "term", "") or ""
            if term:
                tags.append(term.strip())

        return RawNewsItem(
            uid=RawNewsItem.make_uid(link),
            title=title[:300],
            summary=summary[:800],
            link=link,
            source="",          # بعداً توسط fetch() پر می‌شود
            published_dt=published_dt,
            image_url=image_url,
            raw_tags=tags,
            feed_dedicated=True,
            feed_priority=1,
        )

    # ── ابزارهای کمکی ────────────────────────────────────────

    @staticmethod
    def _clean_text(text: str, strip_html: bool = False) -> str:
        """پاک‌سازی متن از HTML و whitespace اضافه"""
        if not text:
            return ""
        if strip_html and ("<" in text and ">" in text):
            try:
                text = BeautifulSoup(text, "html.parser").get_text(separator=" ")
            except Exception:
                text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_url(url: str, base: str) -> str:
        """URL نسبی را به مطلق تبدیل می‌کند"""
        if url.startswith("http"):
            return url
        try:
            return urljoin(base, url)
        except Exception:
            return url

    @staticmethod
    def _parse_date(entry: feedparser.util.FeedParserDict) -> datetime:
        """زمان انتشار را به datetime با timezone UTC تبدیل می‌کند"""
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            t = getattr(entry, attr, None)
            if t:
                try:
                    return datetime(*t[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _extract_image(
        entry: feedparser.util.FeedParserDict, raw_summary: str
    ) -> Optional[str]:
        """
        تصویر خبر را از منابع مختلف استخراج می‌کند:
        1. enclosures (پیوست RSS)
        2. media:content
        3. media:thumbnail
        4. اولین <img> در متن خبر
        """
        # ۱) enclosure
        for enc in getattr(entry, "enclosures", []):
            mime = getattr(enc, "type", "") or ""
            href = getattr(enc, "href", "") or getattr(enc, "url", "") or ""
            if href and "image" in mime:
                return href

        # ۲) media:content
        for mc in getattr(entry, "media_content", []):
            url = mc.get("url", "")
            medium = mc.get("medium", "")
            if url and ("image" in medium or url.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            )):
                return url

        # ۳) media:thumbnail
        thumb = getattr(entry, "media_thumbnail", [])
        if thumb and isinstance(thumb, list) and thumb[0].get("url"):
            return thumb[0]["url"]

        # ۴) اولین تصویر در HTML خبر
        if raw_summary and "<img" in raw_summary:
            try:
                soup = BeautifulSoup(raw_summary, "html.parser")
                img = soup.find("img")
                if img and img.get("src"):
                    src = img["src"]
                    if src.startswith("http"):
                        return src
            except Exception:
                pass

        return None


# ═══════════════════════════════════════════════════════════════
# ۴) تابع اصلی جمع‌آوری موازی
# ═══════════════════════════════════════════════════════════════
def collect_all_feeds() -> list[RawNewsItem]:
    """
    همه فیدها را به صورت موازی دریافت می‌کند.
    خروجی: لیست یکتا از RawNewsItem (بر اساس uid)
    """
    fetcher = AdaptiveFetcher()
    all_items: list[RawNewsItem] = []
    seen_uids: set[str] = set()

    logger.info("🚀 شروع جمع‌آوری از %d فید با %d thread", len(FEEDS), COLLECTOR_MAX_WORKERS)
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=COLLECTOR_MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetcher.fetch, feed): feed
            for feed in sorted(FEEDS, key=lambda f: f.priority)
        }

        for future in as_completed(future_map):
            feed = future_map[future]
            try:
                items = future.result()
                new_count = 0
                for item in items:
                    if item.uid not in seen_uids:
                        seen_uids.add(item.uid)
                        all_items.append(item)
                        new_count += 1
                logger.info("📡 [%s] %d خبر جدید اضافه شد", feed.name, new_count)
            except Exception as exc:
                logger.error("❌ خطا در پردازش فید [%s]: %s", feed.name, exc)

    elapsed = time.time() - start_time
    logger.info(
        "✅ جمع‌آوری کامل: %d خبر یکتا از %d فید | ⏱ %.1f ثانیه",
        len(all_items), len(FEEDS), elapsed,
    )

    # مرتب‌سازی بر اساس تاریخ انتشار (جدیدترین اول)
    all_items.sort(key=lambda x: x.published_dt, reverse=True)
    return all_items
