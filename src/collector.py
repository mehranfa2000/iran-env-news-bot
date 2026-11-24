# src/collector.py
"""
جمع‌آوری اخبار از ۱۴ فید RSS با چندنخی موازی
نسخه ۴.۰
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from agent import NewsItem, make_shamsi
from config import (
    RSS_FEEDS,
    USER_AGENTS,
    COLLECTOR_MAX_WORKERS,
    COLLECTOR_TIMEOUT,
    COLLECTOR_MAX_RETRIES,
)

logger = logging.getLogger("collector")

# چرخش UA
_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


# ══════════════════════════════════════════════════════════════════
# استخراج تصویر
# ══════════════════════════════════════════════════════════════════

def _extract_image(entry: feedparser.FeedParserDict, feed_url: str) -> str:
    """استخراج تصویر از RSS enclosure / media:content / og:image"""

    # ۱. enclosure
    for enc in getattr(entry, "enclosures", []):
        url = enc.get("url", "")
        if url and enc.get("type", "").startswith("image"):
            return url

    # ۲. media_content
    for mc in getattr(entry, "media_content", []):
        url = mc.get("url", "")
        if url and "image" in mc.get("medium", "image"):
            return url

    # ۳. media_thumbnail
    for mt in getattr(entry, "media_thumbnail", []):
        url = mt.get("url", "")
        if url:
            return url

    # ۴. تگ <img> در محتوا
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        content = entry.summary or ""

    if "<" in content and ">" in content:
        try:
            soup = BeautifulSoup(content, "lxml")
            img = soup.find("img")
            if img and img.get("src"):
                return img["src"]
        except Exception:
            pass

    # ۵. og:image از صفحه خبر (تلاش سریع)
    link = getattr(entry, "link", "")
    if link:
        try:
            headers = {"User-Agent": _next_ua()}
            r = requests.get(link, headers=headers, timeout=8, allow_redirects=True)
            if r.status_code == 200 and "<" in r.text:
                soup = BeautifulSoup(r.text, "lxml")
                og = soup.find("meta", property="og:image")
                if og and og.get("content"):
                    return og["content"]
        except Exception:
            pass

    return ""


# ══════════════════════════════════════════════════════════════════
# پارس تاریخ
# ══════════════════════════════════════════════════════════════════

def _parse_published(entry: feedparser.FeedParserDict) -> datetime:
    """استخراج تاریخ انتشار به UTC"""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════
# دریافت یک فید
# ══════════════════════════════════════════════════════════════════

def _fetch_one(feed_cfg: dict) -> list[NewsItem]:
    name        = feed_cfg["name"]
    url         = feed_cfg["url"]
    dedicated   = feed_cfg.get("dedicated", False)
    skip_error  = feed_cfg.get("skip_on_error", False)

    items: list[NewsItem] = []

    for attempt in range(1, COLLECTOR_MAX_RETRIES + 2):
        try:
            headers = {
                "User-Agent": _next_ua(),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "fa,en;q=0.9",
            }
            resp = requests.get(
                url,
                headers=headers,
                timeout=COLLECTOR_TIMEOUT,
                verify=False,
            )
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)

            for entry in parsed.entries:
                link = getattr(entry, "link", "").strip()
                title = getattr(entry, "title", "").strip()
                if not link or not title:
                    continue

                uid = NewsItem.make_uid(link)
                pub_dt = _parse_published(entry)
                shamsi_date, shamsi_time = make_shamsi(pub_dt)

                # خلاصه متنی
                raw_summary = ""
                if hasattr(entry, "summary") and entry.summary:
                    raw_summary = entry.summary
                elif hasattr(entry, "content") and entry.content:
                    raw_summary = entry.content[0].get("value", "")

                if "<" in raw_summary and ">" in raw_summary:
                    try:
                        raw_summary = BeautifulSoup(raw_summary, "lxml").get_text(" ", strip=True)
                    except Exception:
                        raw_summary = re.sub(r"<[^>]+>", " ", raw_summary)
                raw_summary = raw_summary[:500].strip()

                image_url = _extract_image(entry, url)

                news = NewsItem(
                    uid=uid,
                    title=title,
                    link=link,
                    source=name,
                    published_at=pub_dt.isoformat(),
                    shamsi_date=shamsi_date,
                    shamsi_time=shamsi_time,
                    summary=raw_summary,
                    image_url=image_url,
                    category="policy",   # پس از فیلتر تعیین می‌شود
                )
                # ذخیره اطلاعات اضافه برای فیلتر
                news._dedicated = dedicated  # type: ignore[attr-defined]
                items.append(news)

            logger.info("✅ %s — %d خبر", name, len(items))
            return items

        except requests.exceptions.SSLError as e:
            logger.warning("🔐 SSL خطا %s: %s", name, e)
            if skip_error:
                return []
            break
        except requests.exceptions.ConnectionError as e:
            logger.warning("🌐 اتصال خطا %s: %s", name, e)
            if skip_error:
                return []
            if attempt <= COLLECTOR_MAX_RETRIES:
                time.sleep(2 * attempt)
                continue
            break
        except Exception as e:
            logger.warning("⚠️ خطا %s (تلاش %d): %s", name, attempt, e)
            if skip_error:
                return []
            if attempt <= COLLECTOR_MAX_RETRIES:
                time.sleep(2 * attempt)
                continue
            break

    return items


# ══════════════════════════════════════════════════════════════════
# کالکتور اصلی
# ══════════════════════════════════════════════════════════════════

class AdaptiveFetcher:
    """دریافت موازی از ۱۴ فید با ThreadPoolExecutor"""

    def fetch_all(self) -> list[NewsItem]:
        all_items: list[NewsItem] = []
        with ThreadPoolExecutor(max_workers=COLLECTOR_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_one, cfg): cfg["name"] for cfg in RSS_FEEDS}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    all_items.extend(result)
                except Exception as e:
                    logger.error("❌ خطای غیرمنتظره %s: %s", name, e)

        logger.info("📦 مجموع دریافتی: %d خبر از %d فید", len(all_items), len(RSS_FEEDS))
        return all_items
