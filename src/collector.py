# src/collector.py  ·  v4.1  ·  فقط ۱۳ فید اختصاصی محیط‌زیست
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  ۱. تعریف فیدها — فقط ۱۳ فید اختصاصی محیط‌زیست
# ══════════════════════════════════════════════════════════════════

@dataclass
class FeedSource:
    name: str
    url: str
    dedicated: bool = True        # همه اختصاصی → آستانه پایین‌تر
    skip_on_error: bool = False   # برای فیدهای مشکل‌دار

RSS_FEEDS: list[FeedSource] = [
    # ─── ردیف ۱: مهر ───────────────────────────────────────────
    FeedSource(
        name="مهر — محیط‌زیست",
        url="https://www.mehrnews.com/rss/tp/64",
    ),
    # ─── ردیف ۲: همشهری آنلاین ──────────────────────────────────
    FeedSource(
        name="همشهری آنلاین — محیط‌زیست",
        url="https://www.hamshahrionline.ir/rss/tp/584",
    ),
    # ─── ردیف ۳ و ۴: خبرآنلاین ──────────────────────────────────
    FeedSource(
        name="خبرآنلاین — محیط‌زیست",
        url="https://www.khabaronline.ir/rss/tp/44",
    ),
    FeedSource(
        name="خبرآنلاین — طبیعت",
        url="https://www.khabaronline.ir/rss/tp/75",
    ),
    # ─── ردیف ۵ و ۶: سلامت نیوز ─────────────────────────────────
    FeedSource(
        name="سلامت نیوز — محیط‌زیست",
        url="https://www.salamatnews.com/rss/tp/11",
    ),
    FeedSource(
        name="سلامت نیوز — اکوسیستم",
        url="https://www.salamatnews.com/rss/pl/240",
    ),
    # ─── ردیف ۷: ایمنا ───────────────────────────────────────────
    FeedSource(
        name="ایمنا — محیط‌زیست",
        url="https://www.imna.ir/rss/tp/153",
    ),
    # ─── ردیف ۸، ۹، ۱۰: صدا و سیما ──────────────────────────────
    FeedSource(
        name="صدا و سیما — محیط‌زیست (اجتماعی)",
        url="https://www.iribnews.ir/fa/rss/7/39",
    ),
    FeedSource(
        name="صدا و سیما — محیط‌زیست (اقتصادی)",
        url="https://www.iribnews.ir/fa/rss/6/8",
    ),
    FeedSource(
        name="صدا و سیما — آب و انرژی",
        url="https://www.iribnews.ir/fa/rss/6/46",
    ),
    # ─── ردیف ۱۱: YJC ────────────────────────────────────────────
    FeedSource(
        name="باشگاه خبرنگاران — محیط‌زیست",
        url="https://www.yjc.ir/fa/rss/5/74",
        skip_on_error=True,       # ⚠️ 403 از GitHub Actions
    ),
    # ─── ردیف ۱۲: روزنامه حیات ───────────────────────────────────
    FeedSource(
        name="روزنامه حیات — محیط‌زیست",
        url="https://www.hayat.ir/rss/tp/94",
        skip_on_error=True,       # 🆕 فید جدید — احتیاط اولیه
    ),
    # ─── ردیف ۱۳: روزنامه اطلاعات ───────────────────────────────
    FeedSource(
        name="اطلاعات — گردشگری و محیط‌زیست",
        url="https://www.ettelaat.com/rss/tp/65",
        skip_on_error=True,       # 🆕 فید جدید — احتیاط اولیه
    ),
]

# ══════════════════════════════════════════════════════════════════
#  ۲. User-Agent های چرخشی (۶ استراتژی)
# ══════════════════════════════════════════════════════════════════

_USER_AGENTS: list[str] = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Firefox Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.6367.82 Mobile Safari/537.36",
    # Feedparser bot
    "feedparser/6.0.11 +https://github.com/kurtmckee/feedparser",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _make_headers() -> dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }

# ══════════════════════════════════════════════════════════════════
#  ۳. استخراج تصویر از سه منبع
# ══════════════════════════════════════════════════════════════════

def _extract_image_from_entry(entry: feedparser.FeedParserDict) -> Optional[str]:
    """
    الویت:
      1. enclosures (image/*)
      2. media:content
      3. og:image از صفحه خبر
    """
    # --- enclosures ---
    for enc in getattr(entry, "enclosures", []):
        mime = enc.get("type", "")
        url  = enc.get("url", "") or enc.get("href", "")
        if url and mime.startswith("image/"):
            return url

    # --- media:content ---
    media = (
        getattr(entry, "media_content", None)
        or getattr(entry, "media_thumbnail", None)
    )
    if media and isinstance(media, list) and media:
        url = media[0].get("url", "")
        if url:
            return url

    # --- og:image از صفحه ---
    link = entry.get("link", "")
    if link:
        return _fetch_og_image(link)

    return None


def _fetch_og_image(url: str, timeout: int = 6) -> Optional[str]:
    """دریافت og:image از HTML صفحه خبر."""
    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=timeout,
            verify=False,          # برخی سایت‌های ایرانی گواهی خودامضا دارند
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        # هشدار BeautifulSoup را سرکوب می‌کنیم
        if "<" in html and ">" in html:
            soup = BeautifulSoup(html, "lxml")
            tag = soup.find("meta", property="og:image") or \
                  soup.find("meta", attrs={"name": "twitter:image"})
            if tag:
                img_url = tag.get("content", "").strip()
                if img_url.startswith("http"):
                    return img_url
    except Exception as exc:
        logger.debug("og:image fetch failed for %s — %s", url, exc)
    return None

# ══════════════════════════════════════════════════════════════════
#  ۴. ساختار خروجی collector
# ══════════════════════════════════════════════════════════════════

@dataclass
class RawArticle:
    title:     str
    link:      str
    summary:   str
    source:    str
    image_url: Optional[str]
    dedicated: bool
    tags:      list[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════
#  ۵. AdaptiveFetcher — هسته اصلی دریافت موازی
# ══════════════════════════════════════════════════════════════════

class AdaptiveFetcher:
    """
    دریافت موازی RSS با ۶ thread و چرخش User-Agent.
    هر فید حداکثر ۲ بار تلاش می‌کند (retry).
    """

    MAX_WORKERS   = 6
    TIMEOUT_FEED  = 20     # ثانیه — timeout دریافت فید
    RETRY_COUNT   = 2      # تعداد تلاش مجدد
    RETRY_DELAY   = 3.0    # ثانیه بین تلاش‌ها

    def fetch_all(self) -> list[RawArticle]:
        """همه فیدها را موازی دریافت می‌کند."""
        results: list[RawArticle] = []
        total_feeds = len(RSS_FEEDS)

        logger.info("🌐 شروع دریافت %d فید با %d thread", total_feeds, self.MAX_WORKERS)

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {
                pool.submit(self._fetch_one, feed): feed
                for feed in RSS_FEEDS
            }
            for future in as_completed(futures):
                feed = futures[future]
                try:
                    articles = future.result()
                    logger.info(
                        "✅ %-40s → %d خبر",
                        feed.name, len(articles)
                    )
                    results.extend(articles)
                except Exception as exc:
                    if feed.skip_on_error:
                        logger.warning("⚠️ رد شد (skip_on_error): %s — %s", feed.name, exc)
                    else:
                        logger.error("❌ خطا در فید %s — %s", feed.name, exc)

        logger.info("📦 جمع کل مقالات خام: %d", len(results))
        return results

    # ──────────────────────────────────────────────────────────────
    def _fetch_one(self, feed: FeedSource) -> list[RawArticle]:
        """دریافت یک فید با retry و چرخش UA."""
        last_exc: Exception = RuntimeError("نامعلوم")

        for attempt in range(1, self.RETRY_COUNT + 1):
            try:
                return self._parse_feed(feed)
            except Exception as exc:
                last_exc = exc
                if attempt < self.RETRY_COUNT:
                    wait = self.RETRY_DELAY * attempt
                    logger.debug(
                        "🔄 تلاش %d/%d برای %s — %s — انتظار %.1fs",
                        attempt, self.RETRY_COUNT, feed.name, exc, wait
                    )
                    time.sleep(wait)

        # اگر skip_on_error باشد خطا را بالا نمی‌بریم
        if feed.skip_on_error:
            logger.warning("⏭ نادیده گرفته شد: %s", feed.name)
            return []
        raise last_exc

    # ──────────────────────────────────────────────────────────────
    def _parse_feed(self, feed: FeedSource) -> list[RawArticle]:
        """دریافت و parse یک فید RSS."""
        # دریافت محتوای خام با requests (کنترل بهتر روی headers)
        resp = requests.get(
            feed.url,
            headers=_make_headers(),
            timeout=self.TIMEOUT_FEED,
            verify=False,
        )
        resp.raise_for_status()

        # feedparser روی محتوای دریافت‌شده کار می‌کند
        parsed = feedparser.parse(resp.content)

        if parsed.bozo and not parsed.entries:
            raise ValueError(f"feedparser bozo: {parsed.bozo_exception}")

        articles: list[RawArticle] = []

        for entry in parsed.entries:
            title   = self._clean_text(entry.get("title", ""))
            link    = entry.get("link", "").strip()
            summary = self._extract_summary(entry)

            # اعتبارسنجی پایه
            if not title or not link:
                continue
            if not urlparse(link).scheme.startswith("http"):
                continue

            # استخراج تصویر (غیرهمزمان نیست — در thread جداگانه اجرا می‌شود)
            image_url = _extract_image_from_entry(entry)

            # تگ‌های فید
            tags = [
                t.get("term", "")
                for t in getattr(entry, "tags", [])
                if t.get("term")
            ]

            articles.append(RawArticle(
                title     = title,
                link      = link,
                summary   = summary,
                source    = feed.name,
                image_url = image_url,
                dedicated = feed.dedicated,
                tags      = tags,
            ))

        return articles

    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _clean_text(text: str) -> str:
        """پاک‌سازی متن از تگ‌های HTML و فضاهای اضافه."""
        if "<" in text and ">" in text:
            text = BeautifulSoup(text, "lxml").get_text(separator=" ")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_summary(entry: feedparser.FeedParserDict) -> str:
        """استخراج و پاک‌سازی خلاصه خبر."""
        raw = (
            entry.get("summary", "")
            or entry.get("description", "")
            or entry.get("content", [{}])[0].get("value", "")
        )
        if "<" in raw and ">" in raw:
            raw = BeautifulSoup(raw, "lxml").get_text(separator=" ")
        return re.sub(r"\s+", " ", raw).strip()[:500]


# ══════════════════════════════════════════════════════════════════
#  ۶. تابع عمومی — صدا زده می‌شود از main.py
# ══════════════════════════════════════════════════════════════════

def collect_news() -> list[RawArticle]:
    """
    نقطه ورود اصلی collector.
    فراخوانده می‌شود از main.py در فاز ۲.
    """
    fetcher = AdaptiveFetcher()
    return fetcher.fetch_all()
