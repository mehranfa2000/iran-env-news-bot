"""
collector.py — جمع‌آوری موازی RSS با AdaptiveFetcher
نسخه: 4.2.0

تغییرات v4.2:
- Session واحد با connection pooling برای کاهش overhead
- BOM stripping کامل (UTF-8, UTF-16 LE/BE, UTF-32 LE/BE)
- کاراکترهای کنترلی نامعتبر XML پاک می‌شوند
- published_at واقعی از RSS (نه datetime.now)
- استخراج تصویر: media:content → enclosure → og:image → img
- Retry با چرخش User-Agent
- جمع‌آوری موازی با ThreadPoolExecutor
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import warnings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

from src.config import (
    RSS_FEEDS, USER_AGENTS,
    COLLECTOR_MAX_WORKERS, COLLECTOR_TIMEOUT_SEC,
    COLLECTOR_RETRY_COUNT, COLLECTOR_RETRY_DELAY,
    FeedConfig,
)

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# مدل داده خبر خام
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class RawArticle:
    """
    خبر خام از RSS — قبل از فیلتر و تبدیل.

    uid: sha256(link)[:16] — محاسبه در __post_init__
    published_at: زمان واقعی خبر از RSS (ISO 8601 با timezone)
                  اگر RSS نداشت → datetime.now(utc)
    """
    title:        str
    link:         str
    source:       str
    summary:      str                = ""
    image_url:    Optional[str]      = None
    dedicated:    bool               = True
    tags:         list[str]          = field(default_factory=list)
    published_at: str                = ""
    uid:          str                = field(default="", init=False)

    def __post_init__(self) -> None:
        # uid از sha256 لینک — قبل از هر چیز
        self.uid = hashlib.sha256(
            self.link.strip().encode("utf-8")
        ).hexdigest()[:16]

        # اگر published_at نداده شد، زمان فعلی
        if not self.published_at:
            self.published_at = datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# Session با connection pooling
# ══════════════════════════════════════════════════════════════════════════════
def _build_feed_session(ua: str) -> requests.Session:
    """
    Session با:
    - Retry خودکار برای 429/500/502/503/504
    - Connection pooling (10 connections)
    - User-Agent از پارامتر
    """
    session = requests.Session()
    retry = Retry(
        total=COLLECTOR_RETRY_COUNT,
        backoff_factor=COLLECTOR_RETRY_DELAY,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )
    session.mount("http://",  adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent":      ua,
        "Accept":          "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Cache-Control":   "no-cache",
    })
    return session


# ══════════════════════════════════════════════════════════════════════════════
# BOM Stripping و پاکسازی XML
# ══════════════════════════════════════════════════════════════════════════════

# تمام انواع BOM به ترتیب طول (طولانی‌تر اول تا overlap نشود)
_BOM_MARKERS: list[bytes] = [
    b'\x00\x00\xfe\xff',  # UTF-32 BE
    b'\xff\xfe\x00\x00',  # UTF-32 LE
    b'\xef\xbb\xbf',      # UTF-8
    b'\xfe\xff',           # UTF-16 BE
    b'\xff\xfe',           # UTF-16 LE
]


def _strip_bom(content: bytes) -> bytes:
    """تمام انواع BOM را از ابتدای محتوا حذف می‌کند."""
    for bom in _BOM_MARKERS:
        if content.startswith(bom):
            log.debug(f"BOM یافت و حذف شد: {bom.hex()}")
            return content[len(bom):]
    return content


def _sanitize_xml(content: bytes) -> bytes:
    """
    کاراکترهای کنترلی نامعتبر که XML را خراب می‌کنند حذف می‌شوند.
    مجاز: 0x09 (tab), 0x0A (LF), 0x0D (CR), 0x20+
    XML 1.0 spec: #x9 | #xA | #xD | [#x20-#xD7FF] | ...
    """
    # حذف null bytes
    content = content.replace(b'\x00', b'')
    # حذف کاراکترهای کنترلی نامعتبر (به جز tab, newline, CR)
    content = re.sub(rb'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', b'', content)
    return content


def _prepare_content(raw_bytes: bytes) -> bytes:
    """BOM strip + XML sanitize را یکجا اجرا می‌کند."""
    return _sanitize_xml(_strip_bom(raw_bytes))


# ══════════════════════════════════════════════════════════════════════════════
# استخراج زمان انتشار واقعی خبر
# ══════════════════════════════════════════════════════════════════════════════
def _parse_published(entry) -> str:
    """
    زمان انتشار واقعی خبر را از entry استخراج می‌کند.

    اولویت:
    1. published_parsed (struct_time → datetime)
    2. updated_parsed
    3. created_parsed
    4. رشته‌های published/updated (email date format)
    5. dc:date

    اگر هیچ‌کدام نبود → datetime.now(utc)
    """
    # ── struct_time (feedparser parse‌شده) ────────────────────────────────────
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed and len(parsed) >= 6:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                # sanity check: بین سال ۲۰۰۰ و ۲۱۰۰
                if 2000 <= dt.year <= 2100:
                    return dt.isoformat()
            except Exception:
                continue

    # ── رشته‌های خام ─────────────────────────────────────────────────────────
    for attr in ("published", "updated", "dc_date", "created"):
        raw_str: str = getattr(entry, attr, "") or ""
        if not raw_str.strip():
            continue
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if 2000 <= dt.year <= 2100:
                return dt.isoformat()
        except Exception:
            pass
        # تلاش با ISO format
        try:
            dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if 2000 <= dt.year <= 2100:
                return dt.isoformat()
        except Exception:
            pass

    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# استخراج تصویر
# ══════════════════════════════════════════════════════════════════════════════
_IMG_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"})


def _is_image_url(url: str) -> bool:
    """آیا URL احتمالاً یک تصویر است؟"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    path = url.lower().split("?")[0]
    return any(path.endswith(ext) for ext in _IMG_EXTS)


def _extract_image(entry, summary_html: str) -> Optional[str]:
    """
    تصویر را به ترتیب اولویت پیدا می‌کند:
    1. media:content (با mime type تصویر)
    2. media:thumbnail
    3. enclosure (با type image/*)
    4. og:image از HTML summary
    5. اولین <img> با src معتبر
    """
    # ── 1. media:content ──────────────────────────────────────────────────────
    for media in getattr(entry, "media_content", []):
        if isinstance(media, dict):
            url  = media.get("url", "")
            mime = media.get("type", "image/")
            if url and ("image" in mime or _is_image_url(url)):
                return url

    # ── 2. media:thumbnail ────────────────────────────────────────────────────
    thumbnails = getattr(entry, "media_thumbnail", [])
    if thumbnails and isinstance(thumbnails, list):
        url = thumbnails[0].get("url", "")
        if url and url.startswith("http"):
            return url

    # ── 3. enclosure ──────────────────────────────────────────────────────────
    for enc in getattr(entry, "enclosures", []):
        if isinstance(enc, dict):
            url  = enc.get("href", enc.get("url", ""))
            mime = enc.get("type", "image/")
            if url and ("image" in mime or _is_image_url(url)):
                return url

    # ── 4+5. HTML summary ─────────────────────────────────────────────────────
    if summary_html and "<" in summary_html:
        try:
            soup = BeautifulSoup(summary_html, "lxml")

            # og:image
            og = soup.find("meta", attrs={"property": "og:image"})
            if og:
                content = og.get("content", "")
                if content and content.startswith("http"):
                    return content

            # اولین img با src معتبر
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if src.startswith("http"):
                    return src
        except Exception:
            pass

    # ── فیلدهای مستقیم feedparser ─────────────────────────────────────────────
    for attr in ("image", "thumbnail"):
        val = getattr(entry, attr, None)
        if isinstance(val, dict):
            url = val.get("href", val.get("url", ""))
            if url and url.startswith("http"):
                return url
        elif isinstance(val, str) and val.startswith("http"):
            return val

    return None


# ══════════════════════════════════════════════════════════════════════════════
# پاکسازی متن HTML
# ══════════════════════════════════════════════════════════════════════════════
def _clean_text(raw: str) -> str:
    """
    HTML را به متن خالص تبدیل می‌کند.
    اگر HTML tag نداشت، فقط strip می‌کند.
    """
    if not raw:
        return ""
    # فقط اگر واقعاً HTML است (نه متن ساده با < و >)
    if "<" in raw and ">" in raw:
        try:
            soup = BeautifulSoup(raw, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            # فاصله‌های اضافه را پاک کن
            return re.sub(r'\s+', ' ', text).strip()
        except Exception:
            pass
    return raw.strip()


# ══════════════════════════════════════════════════════════════════════════════
# دریافت یک فید (با چندین استراتژی)
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_feed(feed_cfg: FeedConfig, ua_index: int) -> list[RawArticle]:
    """
    یک RSS feed را دریافت، parse و به لیست RawArticle تبدیل می‌کند.

    استراتژی چندمرحله‌ای:
    1. requests با UA[ua_index] + BOM cleanup + feedparser
    2. feedparser مستقیم با UA[ua_index+1]
    3. requests با UA[ua_index+2] (آخرین شانس)

    در هر مرحله:
    - اگر bozo ولی entry وجود داشت → قبول (بعضی فیدها همیشه bozo هستند)
    - اگر bozo و بدون entry → مرحله بعد
    """
    name = feed_cfg.name
    url  = feed_cfg.url
    n_ua = len(USER_AGENTS)

    parsed_feed = None

    # ── استراتژی ۱: requests + cleanup ───────────────────────────────────────
    for attempt in range(COLLECTOR_RETRY_COUNT):
        ua = USER_AGENTS[(ua_index + attempt) % n_ua]
        session = _build_feed_session(ua)
        try:
            resp = session.get(url, timeout=COLLECTOR_TIMEOUT_SEC, verify=False)
            resp.raise_for_status()

            content  = _prepare_content(resp.content)
            feed     = feedparser.parse(content)

            if feed.entries:
                parsed_feed = feed
                log.info(
                    f"✅ [{name}] {len(feed.entries)} خبر"
                    f"{' (bozo)' if feed.bozo else ''}"
                    f" — requests attempt {attempt+1}"
                )
                break
            elif feed.bozo:
                log.debug(f"[{name}] bozo بدون entry (attempt {attempt+1}): "
                          f"{feed.bozo_exception}")
                time.sleep(COLLECTOR_RETRY_DELAY)

        except requests.HTTPError as e:
            log.warning(f"[{name}] HTTP {e.response.status_code} (attempt {attempt+1})")
            if e.response.status_code in (403, 404):
                break   # این‌ها با retry حل نمی‌شوند
            time.sleep(COLLECTOR_RETRY_DELAY)
        except requests.RequestException as e:
            log.debug(f"[{name}] requests خطا (attempt {attempt+1}): {e}")
            time.sleep(COLLECTOR_RETRY_DELAY)
        finally:
            session.close()

        if parsed_feed:
            break

    # ── استراتژی ۲: feedparser مستقیم ────────────────────────────────────────
    if not parsed_feed:
        for i in range(2):
            ua = USER_AGENTS[(ua_index + i + 1) % n_ua]
            try:
                feed = feedparser.parse(url, agent=ua)
                if feed.entries:
                    parsed_feed = feed
                    log.info(f"✅ [{name}] {len(feed.entries)} خبر — feedparser مستقیم")
                    break
            except Exception as e:
                log.debug(f"[{name}] feedparser مستقیم (try {i+1}): {e}")

    # ── شکست کامل ─────────────────────────────────────────────────────────────
    if not parsed_feed or not parsed_feed.entries:
        if feed_cfg.skip_on_error:
            log.warning(f"⚠️  [{name}] رد شد (skip_on_error=True)")
        else:
            log.error(f"❌ [{name}] تمام استراتژی‌ها ناموفق: {url}")
        return []

    # ── تبدیل entry به RawArticle ────────────────────────────────────────────
    articles: list[RawArticle] = []

    for entry in parsed_feed.entries:
        try:
            # ── عنوان ──────────────────────────────────────────────────────────
            title = _clean_text(getattr(entry, "title", "")).strip()
            if not title or len(title) < 5:
                continue

            # ── لینک ───────────────────────────────────────────────────────────
            link = getattr(entry, "link", "").strip()
            if not link or not link.startswith(("http://", "https://")):
                continue

            # ── خلاصه ──────────────────────────────────────────────────────────
            summary_raw = ""
            # اولویت: summary → description → content[0]
            if hasattr(entry, "summary") and entry.summary:
                summary_raw = entry.summary
            elif hasattr(entry, "description") and entry.description:
                summary_raw = entry.description
            elif hasattr(entry, "content") and entry.content:
                summary_raw = entry.content[0].get("value", "")

            summary = _clean_text(summary_raw)[:600]

            # ── تصویر ──────────────────────────────────────────────────────────
            image_url = _extract_image(entry, summary_raw)

            # ── زمان واقعی ─────────────────────────────────────────────────────
            published_at = _parse_published(entry)

            # ── تگ‌ها ───────────────────────────────────────────────────────────
            tags = [
                t.get("term", "").strip()
                for t in getattr(entry, "tags", [])
                if t.get("term", "").strip()
            ]

            articles.append(RawArticle(
                title=title,
                link=link,
                source=name,
                summary=summary,
                image_url=image_url,
                dedicated=feed_cfg.dedicated,
                tags=tags,
                published_at=published_at,
            ))

        except Exception as e:
            log.debug(f"[{name}] خطا در parse entry: {e}")
            continue

    log.debug(f"[{name}] {len(articles)} خبر استخراج شد")
    return articles


# ══════════════════════════════════════════════════════════════════════════════
# جمع‌آوری موازی (تابع اصلی)
# ══════════════════════════════════════════════════════════════════════════════
def collect_all(feeds: Optional[list[FeedConfig]] = None) -> list[RawArticle]:
    """
    همه فیدها را موازی جمع‌آوری می‌کند.

    Args:
        feeds: لیست فیدها؛ اگر None → RSS_FEEDS از config

    Returns:
        لیست RawArticle منحصربه‌فرد (بر اساس link)
    """
    if feeds is None:
        feeds = RSS_FEEDS

    all_articles:  list[RawArticle] = []
    seen_links:    set[str]          = set()
    feed_stats:    dict[str, int]    = {}

    log.info(
        f"🚀 شروع جمع‌آوری موازی — "
        f"{len(feeds)} فید | {COLLECTOR_MAX_WORKERS} thread"
    )
    t0 = time.monotonic()

    with ThreadPoolExecutor(
        max_workers=COLLECTOR_MAX_WORKERS,
        thread_name_prefix="collector",
    ) as executor:
        # submit با چرخش UA index
        future_map = {
            executor.submit(_fetch_feed, feed_cfg, i): feed_cfg
            for i, feed_cfg in enumerate(feeds)
        }

        for future in as_completed(future_map, timeout=120):
            feed_cfg = future_map[future]
            try:
                articles = future.result(timeout=5)
                new_count = 0

                for art in articles:
                    if art.link not in seen_links:
                        seen_links.add(art.link)
                        all_articles.append(art)
                        new_count += 1

                feed_stats[feed_cfg.name] = new_count

            except FuturesTimeout:
                log.warning(f"⏰ [{feed_cfg.name}] timeout در future.result()")
            except Exception as e:
                log.error(f"❌ [{feed_cfg.name}] خطای کلی: {e}")
                feed_stats[feed_cfg.name] = 0

    elapsed = time.monotonic() - t0

    # ── گزارش خلاصه ───────────────────────────────────────────────────────────
    log.info(
        f"✅ جمع‌آوری تمام — "
        f"{len(all_articles)} خبر منحصربه‌فرد | "
        f"{elapsed:.1f}s"
    )

    # خلاصه هر فید
    for feed_name, count in sorted(feed_stats.items(), key=lambda x: -x[1]):
        icon = "✅" if count > 0 else "⚠️ "
        log.debug(f"   {icon} {feed_name}: {count} خبر")

    return all_articles
