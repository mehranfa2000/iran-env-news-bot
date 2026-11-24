# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/collector.py  ·  v4.1  ·  جمع‌آوری موازی اخبار محیط‌زیست              ║
# ║  ۱۳ فید اختصاصی · 6 thread · 6 UA · استخراج تصویر · uid خودکار            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
import urllib3
from bs4 import BeautifulSoup

# حذف هشدار SSL برای سایت‌های ایرانی با گواهی خودامضا
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="bs4")

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. تعریف منابع RSS — 13 فید اختصاصی محیط‌زیست
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FeedSource:
    """تعریف یک منبع RSS."""
    name:          str
    url:           str
    dedicated:     bool = True    # اختصاصی → آستانه فیلتر پایین‌تر
    skip_on_error: bool = False   # در صورت خطا رد شود (crash نکند)
    verify_ssl:    bool = False   # اکثر سایت‌های ایرانی گواهی مشکل دارند


RSS_FEEDS: list[FeedSource] = [

    # ── ۱. مهر ──────────────────────────────────────────────────────────────
    FeedSource(
        name="مهر — محیط‌زیست",
        url="https://www.mehrnews.com/rss/tp/64",
    ),

    # ── ۲. همشهری آنلاین ────────────────────────────────────────────────────
    FeedSource(
        name="همشهری آنلاین — محیط‌زیست",
        url="https://www.hamshahrionline.ir/rss/tp/584",
    ),

    # ── ۳. خبرآنلاین — محیط‌زیست ────────────────────────────────────────────
    FeedSource(
        name="خبرآنلاین — محیط‌زیست",
        url="https://www.khabaronline.ir/rss/tp/44",
    ),

    # ── ۴. خبرآنلاین — طبیعت ────────────────────────────────────────────────
    FeedSource(
        name="خبرآنلاین — طبیعت",
        url="https://www.khabaronline.ir/rss/tp/75",
    ),

    # ── ۵. سلامت نیوز — محیط‌زیست ───────────────────────────────────────────
    FeedSource(
        name="سلامت نیوز — محیط‌زیست",
        url="https://www.salamatnews.com/rss/tp/11",
    ),

    # ── ۶. سلامت نیوز — اکوسیستم ────────────────────────────────────────────
    FeedSource(
        name="سلامت نیوز — اکوسیستم",
        url="https://www.salamatnews.com/rss/pl/240",
    ),

    # ── ۷. ایمنا — محیط‌زیست ────────────────────────────────────────────────
    FeedSource(
        name="ایمنا — محیط‌زیست",
        url="https://www.imna.ir/rss/tp/153",
    ),

    # ── ۸. صدا و سیما — محیط‌زیست (اجتماعی) ────────────────────────────────
    FeedSource(
        name="صدا و سیما — محیط‌زیست (اجتماعی)",
        url="https://www.iribnews.ir/fa/rss/7/39",
    ),

    # ── ۹. صدا و سیما — محیط‌زیست (اقتصادی) ────────────────────────────────
    FeedSource(
        name="صدا و سیما — محیط‌زیست (اقتصادی)",
        url="https://www.iribnews.ir/fa/rss/6/8",
    ),

    # ── ۱۰. صدا و سیما — آب و انرژی ─────────────────────────────────────────
    FeedSource(
        name="صدا و سیما — آب و انرژی",
        url="https://www.iribnews.ir/fa/rss/6/46",
    ),

    # ── ۱۱. باشگاه خبرنگاران (YJC) ──────────────────────────────────────────
    # ⚠️ HTTP 403 از GitHub Actions — skip_on_error=True
    FeedSource(
        name="باشگاه خبرنگاران — محیط‌زیست",
        url="https://www.yjc.ir/fa/rss/5/74",
        skip_on_error=True,
    ),

    # ── ۱۲. روزنامه حیات ─────────────────────────────────────────────────────
    # 🆕 فید جدید — احتیاط اولیه
    FeedSource(
        name="روزنامه حیات — محیط‌زیست",
        url="https://www.hayat.ir/rss/tp/94",
        skip_on_error=True,
    ),

    # ── ۱۳. روزنامه اطلاعات ──────────────────────────────────────────────────
    # 🆕 فید جدید — احتیاط اولیه
    FeedSource(
        name="اطلاعات — گردشگری و محیط‌زیست",
        url="https://www.ettelaat.com/rss/tp/65",
        skip_on_error=True,
    ),
]

# ══════════════════════════════════════════════════════════════════════════════
#  ۲. User-Agent های چرخشی — ۶ استراتژی
# ══════════════════════════════════════════════════════════════════════════════

_USER_AGENTS: list[str] = [
    # ۱. Chrome / Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # ۲. Firefox / Linux
    (
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    # ۳. Safari / macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    # ۴. Edge / Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
    # ۵. Chrome / Android
    (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.82 Mobile Safari/537.36"
    ),
    # ۶. feedparser bot
    "feedparser/6.0.11 +https://github.com/kurtmckee/feedparser",
]


def _random_ua() -> str:
    """انتخاب تصادفی یک User-Agent."""
    return random.choice(_USER_AGENTS)


def _make_headers() -> dict[str, str]:
    """ساخت header کامل برای هر درخواست."""
    return {
        "User-Agent":      _random_ua(),
        "Accept":          "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control":   "no-cache",
        "Pragma":          "no-cache",
        "Connection":      "keep-alive",
    }

# ══════════════════════════════════════════════════════════════════════════════
#  ۳. ساختار داده خروجی — RawArticle با uid خودکار
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RawArticle:
    """
    یک خبر خام دریافت‌شده از RSS.
    uid به صورت خودکار از sha256 لینک محاسبه می‌شود.
    """
    title:     str
    link:      str
    summary:   str
    source:    str
    image_url: Optional[str]
    dedicated: bool
    tags:      list[str] = field(default_factory=list)

    # ── uid: محاسبه خودکار — نیازی به مقداردهی دستی نیست ──
    uid: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        """
        بلافاصله بعد از ساخت شیء، uid محاسبه می‌شود.
        فرمول: sha256(link.encode)[:16]  → ۱۶ کاراکتر یکتا
        همان فرمولی که StorageManager در agent.py استفاده می‌کند.
        """
        self.uid = hashlib.sha256(
            self.link.strip().encode("utf-8")
        ).hexdigest()[:16]

# ══════════════════════════════════════════════════════════════════════════════
#  ۴. استخراج تصویر — ۳ لایه (enclosure → media → og:image)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_image_from_entry(entry: feedparser.FeedParserDict) -> Optional[str]:
    """
    الویت استخراج تصویر:
      لایه ۱ → enclosures  (image/*)
      لایه ۲ → media:content / media:thumbnail
      لایه ۳ → og:image از صفحه HTML خبر
    """

    # ── لایه ۱: enclosures ──────────────────────────────────────────────────
    for enc in getattr(entry, "enclosures", []):
        mime = enc.get("type", "")
        url  = enc.get("url", "") or enc.get("href", "")
        if url and mime.startswith("image/"):
            logger.debug("🖼 تصویر از enclosure: %s", url)
            return _validate_image_url(url)

    # ── لایه ۲: media:content / media:thumbnail ─────────────────────────────
    for attr in ("media_content", "media_thumbnail"):
        media_list = getattr(entry, attr, None)
        if media_list and isinstance(media_list, list):
            url = media_list[0].get("url", "")
            if url:
                logger.debug("🖼 تصویر از %s: %s", attr, url)
                return _validate_image_url(url)

    # ── لایه ۳: og:image از HTML صفحه ──────────────────────────────────────
    link = entry.get("link", "").strip()
    if link:
        og = _fetch_og_image(link)
        if og:
            return og

    return None


def _validate_image_url(url: str) -> Optional[str]:
    """بررسی می‌کند URL تصویر معتبر است."""
    url = url.strip()
    if url.startswith("http") and any(
        ext in url.lower()
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", "image", "photo", "pic")
    ):
        return url
    # اگر پسوند ندارد ولی http دارد، باز هم قبول می‌کنیم
    if url.startswith("http"):
        return url
    return None


def _fetch_og_image(url: str, timeout: int = 7) -> Optional[str]:
    """
    دریافت og:image از HTML صفحه خبر.
    اول <meta property="og:image"> سپس <meta name="twitter:image">
    """
    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=timeout,
            verify=False,
            allow_redirects=True,
            stream=False,
        )
        resp.raise_for_status()

        # فقط اگر HTML است parse کن
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "xml" not in content_type:
            return None

        html = resp.text
        if "<" not in html or ">" not in html:
            return None

        soup = BeautifulSoup(html, "lxml")

        # جستجو در ترتیب اولویت
        selectors = [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
            {"itemprop": "image"},
        ]
        for attrs in selectors:
            tag = soup.find("meta", attrs=attrs)
            if tag:
                img_url = (tag.get("content") or tag.get("href") or "").strip()
                if img_url.startswith("http"):
                    logger.debug("🖼 og:image یافت شد: %s", img_url)
                    return img_url

    except requests.exceptions.Timeout:
        logger.debug("⏱ timeout دریافت og:image از %s", url)
    except requests.exceptions.SSLError:
        logger.debug("🔒 خطای SSL در دریافت og:image از %s", url)
    except Exception as exc:
        logger.debug("⚠️ خطا در og:image از %s — %s", url, exc)

    return None

# ══════════════════════════════════════════════════════════════════════════════
#  ۵. توابع کمکی پاک‌سازی متن
# ══════════════════════════════════════════════════════════════════════════════

def _clean_text(text: str) -> str:
    """پاک‌سازی تگ‌های HTML و فضاهای اضافه از متن."""
    if not text:
        return ""
    if "<" in text and ">" in text:
        try:
            text = BeautifulSoup(text, "lxml").get_text(separator=" ")
        except Exception:
            # fallback: پاک‌سازی دستی تگ‌ها
            text = re.sub(r"<[^>]+>", " ", text)
    # پاک‌سازی کاراکترهای کنترلی و فضاهای اضافه
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_summary(entry: feedparser.FeedParserDict) -> str:
    """
    استخراج خلاصه خبر با اولویت‌بندی:
    summary → description → content[0].value
    """
    # الویت ۱: summary
    raw = entry.get("summary", "")

    # الویت ۲: description
    if not raw:
        raw = entry.get("description", "")

    # الویت ۳: content
    if not raw:
        content_list = entry.get("content", [])
        if content_list and isinstance(content_list, list):
            raw = content_list[0].get("value", "")

    cleaned = _clean_text(raw)

    # حداکثر ۵۰۰ کاراکتر — کافی برای فیلتر + ارسال
    return cleaned[:500]

# ══════════════════════════════════════════════════════════════════════════════
#  ۶. AdaptiveFetcher — هسته اصلی دریافت موازی
# ══════════════════════════════════════════════════════════════════════════════

class AdaptiveFetcher:
    """
    دریافت موازی ۱۳ فید RSS با:
    - ۶ thread همزمان
    - چرخش ۶ User-Agent
    - ۲ بار retry با تاخیر نمایی
    - مدیریت هوشمند خطا (skip_on_error)
    - استخراج ۳ لایه‌ای تصویر
    - uid خودکار برای هر خبر
    """

    MAX_WORKERS:  int   = 6
    TIMEOUT_FEED: int   = 25     # ثانیه — timeout دریافت فید
    RETRY_COUNT:  int   = 2      # تعداد تلاش مجدد
    RETRY_DELAY:  float = 3.0    # ثانیه — تاخیر بین تلاش‌ها

    # ──────────────────────────────────────────────────────────────────────────
    def fetch_all(self) -> list[RawArticle]:
        """
        نقطه ورود اصلی:
        همه فیدها را موازی دریافت و لیست RawArticle برمی‌گرداند.
        """
        total = len(RSS_FEEDS)
        logger.info("🌐 شروع دریافت %d فید با %d thread", total, self.MAX_WORKERS)

        results:   list[RawArticle] = []
        success:   int = 0
        failed:    int = 0
        skipped:   int = 0

        with ThreadPoolExecutor(
            max_workers=self.MAX_WORKERS,
            thread_name_prefix="collector",
        ) as pool:

            futures = {
                pool.submit(self._fetch_one, feed): feed
                for feed in RSS_FEEDS
            }

            for future in as_completed(futures):
                feed = futures[future]
                try:
                    articles = future.result()
                    count = len(articles)
                    logger.info(
                        "✅ %-42s → %3d خبر",
                        feed.name, count
                    )
                    results.extend(articles)
                    if count >= 0:
                        success += 1

                except FeedSkippedError as exc:
                    logger.warning("⏭  رد شد (skip_on_error): %-30s — %s", feed.name, exc)
                    skipped += 1

                except Exception as exc:
                    logger.error("❌ خطای کشنده فید %-30s — %s", feed.name, exc)
                    failed += 1

        logger.info(
            "📦 جمع خام: %d خبر | ✅ %d فید | ⏭ %d رد | ❌ %d خطا",
            len(results), success, skipped, failed
        )
        return results

    # ──────────────────────────────────────────────────────────────────────────
    def _fetch_one(self, feed: FeedSource) -> list[RawArticle]:
        """
        دریافت یک فید با مکانیزم retry.
        در صورت skip_on_error، به جای raise، لیست خالی برمی‌گرداند.
        """
        last_exc: Exception = RuntimeError("نامعلوم")

        for attempt in range(1, self.RETRY_COUNT + 1):
            try:
                return self._parse_feed(feed)

            except Exception as exc:
                last_exc = exc
                is_last = attempt == self.RETRY_COUNT

                if is_last:
                    break

                wait = self.RETRY_DELAY * attempt
                logger.debug(
                    "🔄 تلاش %d/%d | %s | خطا: %s | انتظار: %.1fs",
                    attempt, self.RETRY_COUNT,
                    feed.name, exc, wait
                )
                time.sleep(wait)

        # پس از تمام تلاش‌ها:
        if feed.skip_on_error:
            raise FeedSkippedError(str(last_exc)) from last_exc

        raise last_exc

    # ──────────────────────────────────────────────────────────────────────────
    def _parse_feed(self, feed: FeedSource) -> list[RawArticle]:
        """
        دریافت محتوای RSS با requests و parse با feedparser.
        استخراج تصویر برای هر entry.
        """
        # دریافت محتوای خام — requests کنترل بهتری روی headers دارد
        resp = requests.get(
            feed.url,
            headers=_make_headers(),
            timeout=self.TIMEOUT_FEED,
            verify=feed.verify_ssl,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # feedparser روی bytes کار می‌کند (تشخیص encoding بهتر)
        parsed = feedparser.parse(resp.content)

        # بررسی bozo (فید خراب)
        if parsed.bozo and not parsed.entries:
            exc = getattr(parsed, "bozo_exception", "نامعلوم")
            raise ValueError(f"فید خراب — bozo: {exc}")

        articles: list[RawArticle] = []

        for entry in parsed.entries:
            article = self._entry_to_article(entry, feed)
            if article is not None:
                articles.append(article)

        return articles

    # ──────────────────────────────────────────────────────────────────────────
    def _entry_to_article(
        self,
        entry: feedparser.FeedParserDict,
        feed:  FeedSource,
    ) -> Optional[RawArticle]:
        """
        تبدیل یک entry فید به RawArticle.
        در صورت اعتبارسنجی شکست → None برمی‌گرداند.
        """
        # ── استخراج فیلدهای اصلی ────────────────────────────────────────────
        title   = _clean_text(entry.get("title", ""))
        link    = entry.get("link", "").strip()
        summary = _extract_summary(entry)

        # ── اعتبارسنجی پایه ─────────────────────────────────────────────────
        if not title:
            return None
        if not link:
            return None
        parsed_url = urlparse(link)
        if parsed_url.scheme not in ("http", "https"):
            return None
        if not parsed_url.netloc:
            return None

        # ── استخراج تصویر (۳ لایه) ──────────────────────────────────────────
        image_url = _extract_image_from_entry(entry)

        # ── استخراج تگ‌ها ────────────────────────────────────────────────────
        tags: list[str] = []
        for t in getattr(entry, "tags", []):
            term = t.get("term", "").strip()
            if term:
                tags.append(term)

        # ── ساخت RawArticle — uid خودکار در __post_init__ ───────────────────
        return RawArticle(
            title     = title,
            link      = link,
            summary   = summary,
            source    = feed.name,
            image_url = image_url,
            dedicated = feed.dedicated,
            tags      = tags,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ۷. خطای اختصاصی skip
# ══════════════════════════════════════════════════════════════════════════════

class FeedSkippedError(Exception):
    """وقتی یک فید skip_on_error=True است و خطا می‌دهد."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  ۸. تابع عمومی — فراخوانده می‌شود از main.py در فاز ۲
# ══════════════════════════════════════════════════════════════════════════════

def collect_news() -> list[RawArticle]:
    """
    نقطه ورود اصلی collector.
    فراخوانده می‌شود از main.py:
        from src.collector import collect_news
        raw_items = collect_news()
    """
    fetcher = AdaptiveFetcher()
    articles = fetcher.fetch_all()

    # گزارش نهایی آماری
    dedicated_count = sum(1 for a in articles if a.dedicated)
    with_image      = sum(1 for a in articles if a.image_url)

    logger.info(
        "📊 آمار collector — کل: %d | اختصاصی: %d | با تصویر: %d | بدون تصویر: %d",
        len(articles),
        dedicated_count,
        with_image,
        len(articles) - with_image,
    )

    return articles
