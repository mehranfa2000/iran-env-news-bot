# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/collector.py  ·  v4.2  ·  جمع‌آوری موازی اخبار محیط‌زیست              ║
# ║  ۱۳ فید اختصاصی · 6 thread · 6 UA · استخراج تصویر · uid خودکار            ║
# ║  رفع: BOM مهر · bozo fallback · InsecureRequestWarning                      ║
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

# ── حذف هشدارهای غیرضروری ────────────────────────────────────────────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="bs4")

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. تعریف منابع RSS — 13 فید اختصاصی محیط‌زیست
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FeedSource:
    """تعریف یک منبع RSS با تمام تنظیمات آن."""
    name:          str
    url:           str
    dedicated:     bool = True    # اختصاصی → آستانه فیلتر پایین‌تر
    skip_on_error: bool = False   # در صورت خطا crash نکند
    verify_ssl:    bool = False   # اکثر سایت‌های ایرانی گواهی SSL مشکل دارند


RSS_FEEDS: list[FeedSource] = [

    # ── ۱. مهر ──────────────────────────────────────────────────────────────
    FeedSource(
        name="مهر — محیط‌زیست",
        url="https://www.mehrnews.com/rss/tp/64",
        skip_on_error=True,   # گاهی BOM/bozo می‌دهد → fallback داریم
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
    # ⚠️ HTTP 403 از GitHub Actions
    FeedSource(
        name="باشگاه خبرنگاران — محیط‌زیست",
        url="https://www.yjc.ir/fa/rss/5/74",
        skip_on_error=True,
    ),

    # ── ۱۲. روزنامه حیات ─────────────────────────────────────────────────────
    FeedSource(
        name="روزنامه حیات — محیط‌زیست",
        url="https://www.hayat.ir/rss/tp/94",
        skip_on_error=True,
    ),

    # ── ۱۳. روزنامه اطلاعات ──────────────────────────────────────────────────
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
    """ساخت header کامل برای هر درخواست HTTP."""
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

    uid: خودکار از sha256(link)[:16] محاسبه می‌شود.
    دقیقاً همان فرمولی که StorageManager در agent.py استفاده می‌کند
    تا تشخیص تکراری صحیح باشد.
    """
    title:     str
    link:      str
    summary:   str
    source:    str
    image_url: Optional[str]
    dedicated: bool
    tags:      list[str] = field(default_factory=list)

    # uid: خودکار — نیازی به مقداردهی دستی نیست
    uid: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        """uid بلافاصله بعد از ساخت شیء محاسبه می‌شود."""
        self.uid = hashlib.sha256(
            self.link.strip().encode("utf-8")
        ).hexdigest()[:16]

# ══════════════════════════════════════════════════════════════════════════════
#  ۴. استخراج تصویر — ۳ لایه
# ══════════════════════════════════════════════════════════════════════════════

def _extract_image_from_entry(entry: feedparser.FeedParserDict) -> Optional[str]:
    """
    استخراج تصویر با ۳ لایه اولویت:
      لایه ۱ → enclosures  (image/*)
      لایه ۲ → media:content / media:thumbnail
      لایه ۳ → og:image از HTML صفحه خبر
    """

    # ── لایه ۱: enclosures ──────────────────────────────────────────────────
    for enc in getattr(entry, "enclosures", []):
        mime = enc.get("type", "")
        url  = enc.get("url", "") or enc.get("href", "")
        if url and mime.startswith("image/"):
            validated = _validate_image_url(url)
            if validated:
                logger.debug("🖼 enclosure: %s", validated)
                return validated

    # ── لایه ۲: media:content / media:thumbnail ─────────────────────────────
    for attr in ("media_content", "media_thumbnail"):
        media_list = getattr(entry, attr, None)
        if media_list and isinstance(media_list, list) and media_list:
            url = media_list[0].get("url", "")
            if url:
                validated = _validate_image_url(url)
                if validated:
                    logger.debug("🖼 %s: %s", attr, validated)
                    return validated

    # ── لایه ۳: og:image از HTML صفحه ──────────────────────────────────────
    link = entry.get("link", "").strip()
    if link:
        og = _fetch_og_image(link)
        if og:
            return og

    return None


def _validate_image_url(url: str) -> Optional[str]:
    """بررسی می‌کند URL تصویر با http شروع می‌شود."""
    url = url.strip()
    if url.startswith("http"):
        return url
    return None


def _fetch_og_image(url: str, timeout: int = 7) -> Optional[str]:
    """
    دریافت og:image یا twitter:image از HTML صفحه خبر.
    با ترتیب اولویت meta tag ها جستجو می‌کند.
    """
    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=timeout,
            verify=False,
            allow_redirects=True,
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

        # ترتیب اولویت meta tagها
        selectors = [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
            {"itemprop": "image"},
        ]
        for attrs in selectors:
            tag = soup.find("meta", attrs=attrs)
            if tag:
                img_url = (
                    tag.get("content") or tag.get("href") or ""
                ).strip()
                if img_url.startswith("http"):
                    logger.debug("🖼 og:image: %s", img_url)
                    return img_url

    except requests.exceptions.Timeout:
        logger.debug("⏱ timeout og:image از %s", url)
    except requests.exceptions.SSLError:
        logger.debug("🔒 SSL og:image از %s", url)
    except Exception as exc:
        logger.debug("⚠️ og:image خطا از %s — %s", url, exc)

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
            text = re.sub(r"<[^>]+>", " ", text)
    # حذف کاراکترهای کنترلی
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_summary(entry: feedparser.FeedParserDict) -> str:
    """
    استخراج خلاصه خبر با اولویت:
    summary → description → content[0].value
    حداکثر ۵۰۰ کاراکتر.
    """
    raw = entry.get("summary", "")

    if not raw:
        raw = entry.get("description", "")

    if not raw:
        content_list = entry.get("content", [])
        if content_list and isinstance(content_list, list):
            raw = content_list[0].get("value", "")

    cleaned = _clean_text(raw)
    return cleaned[:500]

# ══════════════════════════════════════════════════════════════════════════════
#  ۶. خطای اختصاصی skip
# ══════════════════════════════════════════════════════════════════════════════

class FeedSkippedError(Exception):
    """وقتی فید skip_on_error=True است و خطا می‌دهد."""
    pass

# ══════════════════════════════════════════════════════════════════════════════
#  ۷. AdaptiveFetcher — هسته اصلی دریافت موازی
# ══════════════════════════════════════════════════════════════════════════════

class AdaptiveFetcher:
    """
    دریافت موازی ۱۳ فید RSS با:
    · ۶ thread همزمان
    · چرخش ۶ User-Agent
    · ۲ بار retry با تاخیر نمایی
    · رفع BOM (عامل خطای مهر)
    · bozo fallback (feedparser مستقیم)
    · مدیریت skip_on_error
    · استخراج ۳ لایه‌ای تصویر
    · uid خودکار برای هر خبر
    """

    MAX_WORKERS:  int   = 6
    TIMEOUT_FEED: int   = 25
    RETRY_COUNT:  int   = 2
    RETRY_DELAY:  float = 3.0

    # ──────────────────────────────────────────────────────────────────────────
    def fetch_all(self) -> list[RawArticle]:
        """دریافت موازی همه فیدها و بازگرداندن لیست RawArticle."""
        total = len(RSS_FEEDS)
        logger.info("🌐 شروع دریافت %d فید با %d thread", total, self.MAX_WORKERS)

        results: list[RawArticle] = []
        success  = 0
        skipped  = 0
        failed   = 0

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
                    logger.info(
                        "✅ %-42s → %3d خبر",
                        feed.name, len(articles)
                    )
                    results.extend(articles)
                    success += 1

                except FeedSkippedError as exc:
                    logger.warning(
                        "⏭  رد شد: %-35s — %s",
                        feed.name, exc
                    )
                    skipped += 1

                except Exception as exc:
                    logger.error(
                        "❌ خطا: %-35s — %s",
                        feed.name, exc
                    )
                    failed += 1

        logger.info(
            "📦 جمع خام: %d خبر | ✅ %d فید | ⏭ %d رد | ❌ %d خطا",
            len(results), success, skipped, failed
        )

        # آمار تصویر
        with_image = sum(1 for a in results if a.image_url)
        logger.info(
            "🖼 تصویر: %d دارند | %d ندارند",
            with_image, len(results) - with_image
        )

        return results

    # ──────────────────────────────────────────────────────────────────────────
    def _fetch_one(self, feed: FeedSource) -> list[RawArticle]:
        """دریافت یک فید با مکانیزم retry."""
        last_exc: Exception = RuntimeError("نامعلوم")

        for attempt in range(1, self.RETRY_COUNT + 1):
            try:
                return self._parse_feed(feed)

            except Exception as exc:
                last_exc = exc
                if attempt < self.RETRY_COUNT:
                    wait = self.RETRY_DELAY * attempt
                    logger.debug(
                        "🔄 تلاش %d/%d | %s | %s | انتظار %.1fs",
                        attempt, self.RETRY_COUNT,
                        feed.name, exc, wait
                    )
                    time.sleep(wait)

        # بعد از همه تلاش‌ها:
        if feed.skip_on_error:
            raise FeedSkippedError(str(last_exc)) from last_exc
        raise last_exc

    # ──────────────────────────────────────────────────────────────────────────
    def _parse_feed(self, feed: FeedSource) -> list[RawArticle]:
        """
        دریافت محتوای RSS با requests و parse با feedparser.

        رفع مشکل BOM:
            برخی فیدهای ایرانی (مثل مهر) با BOM شروع می‌کنند.
            BOM یک کاراکتر نامرئی در ابتدای فایل XML است که
            feedparser را گیج می‌کند و خطای bozo می‌دهد.
            راه‌حل: strip کردن BOM قبل از parse.

        رفع مشکل bozo:
            اگر بعد از strip BOM هنوز bozo بود ولی entry داشت →
            همان entry‌ها را قبول می‌کنیم.
            اگر entry نداشت → feedparser را مستقیم روی URL امتحان می‌کنیم.
        """

        # ── دریافت محتوای خام ────────────────────────────────────────────────
        resp = requests.get(
            feed.url,
            headers=_make_headers(),
            timeout=self.TIMEOUT_FEED,
            verify=feed.verify_ssl,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content = resp.content

        # ── رفع BOM ──────────────────────────────────────────────────────────
        # BOMهای رایج: UTF-8 (EF BB BF) | UTF-16 LE (FF FE) | UTF-16 BE (FE FF)
        bom_map = {
            b"\xef\xbb\xbf": "UTF-8 BOM",
            b"\xff\xfe":     "UTF-16 LE BOM",
            b"\xfe\xff":     "UTF-16 BE BOM",
        }
        for bom_bytes, bom_name in bom_map.items():
            if content.startswith(bom_bytes):
                content = content[len(bom_bytes):]
                logger.debug("🔧 %s حذف شد از %s", bom_name, feed.name)
                break

        # ── parse با feedparser ──────────────────────────────────────────────
        parsed = feedparser.parse(content)

        # ── مدیریت bozo ──────────────────────────────────────────────────────
        if parsed.bozo:
            bozo_exc = getattr(parsed, "bozo_exception", "نامعلوم")

            if parsed.entries:
                # فید مشکل فرمت دارد ولی خبر دارد → قبول می‌کنیم
                logger.warning(
                    "⚠️ bozo فید %s (%d entry) — %s",
                    feed.name, len(parsed.entries), bozo_exc
                )
            else:
                # fallback: feedparser مستقیم روی URL
                logger.debug("🔄 fallback feedparser مستقیم: %s", feed.name)
                parsed_direct = feedparser.parse(
                    feed.url,
                    agent=_random_ua(),
                )
                if parsed_direct.entries:
                    parsed = parsed_direct
                    logger.info("✅ fallback موفق: %s (%d entry)",
                                feed.name, len(parsed.entries))
                else:
                    raise ValueError(
                        f"فید خراب — bozo: {bozo_exc}"
                    )

        # ── تبدیل entry‌ها به RawArticle ─────────────────────────────────────
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
        در صورت اعتبارسنجی شکست → None.
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

        # ── استخراج تصویر ───────────────────────────────────────────────────
        image_url = _extract_image_from_entry(entry)

        # ── استخراج تگ‌ها ────────────────────────────────────────────────────
        tags: list[str] = [
            t.get("term", "").strip()
            for t in getattr(entry, "tags", [])
            if t.get("term", "").strip()
        ]

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
#  ۸. تابع عمومی — فراخوانده می‌شود از main.py
# ══════════════════════════════════════════════════════════════════════════════

def collect_news() -> list[RawArticle]:
    """
    نقطه ورود اصلی collector.

    استفاده در main.py:
        from src.collector import collect_news
        raw_items = collect_news()
    """
    fetcher = AdaptiveFetcher()
    return fetcher.fetch_all()
