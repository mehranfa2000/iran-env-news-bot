# ============================================================
#  src/collector.py — جمع‌آوری از ۱۱ فید RSS
#  استانداردهای 2026: User-Agent rotation، retry، backoff
# ============================================================

import time
import feedparser
import requests
from bs4 import BeautifulSoup

# ── ۱۱ فید RSS تأییدشده ─────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://www.irna.ir/rss/tp/32",              "source": "ایرنا",                  "dedicated": True},
    {"url": "https://www.mehrnews.com/rss/tp/64",         "source": "مهر",                    "dedicated": True},
    {"url": "https://www.hamshahrionline.ir/rss/tp/584",  "source": "همشهری",                 "dedicated": True},
    {"url": "https://www.khabaronline.ir/rss/tp/44",      "source": "خبرآنلاین",              "dedicated": True},
    {"url": "https://www.imna.ir/rss/tp/153",             "source": "ایمنا",                  "dedicated": True},
    {"url": "https://www.yjc.ir/fa/rss/5/74",             "source": "باشگاه خبرنگاران",       "dedicated": True},
    {"url": "https://www.ettelaat.com/rss/tp/65",         "source": "اطلاعات",                "dedicated": True},
    {"url": "https://www.iribnews.ir/fa/rss/7/39",        "source": "صدا و سیما",             "dedicated": True},
    {"url": "https://www.iribnews.ir/fa/rss/6/8",         "source": "صدا و سیما آب و انرژی", "dedicated": True},
    {"url": "https://www.salamatnews.com/rss/tp/11",      "source": "سلامت نیوز",             "dedicated": True},
    {"url": "https://www.isna.ir/rss",                    "source": "ایسنا",                  "dedicated": False},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]
_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        try:
            return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            return raw
    return raw.strip()


def _fetch(url: str, source: str, retries: int = 3) -> list:
    headers = {
        "User-Agent": _next_ua(),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "fa,en;q=0.9",
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            if r.status_code == 403:
                print(f"    ⛔ {source}: 403 — رد می‌شود")
                return []
            if r.status_code != 200:
                print(f"    ⚠️  {source}: HTTP {r.status_code} (تلاش {attempt}/{retries})")
                time.sleep(2 ** attempt)
                continue
            feed = feedparser.parse(r.content)
            if not feed.entries:
                print(f"    ⚠️  {source}: فید خالی")
                return []
            print(f"    ✅ {source}: {len(feed.entries)} خبر")
            return feed.entries
        except requests.exceptions.Timeout:
            print(f"    ⏱️  {source}: timeout (تلاش {attempt}/{retries})")
        except requests.exceptions.ConnectionError:
            print(f"    🔌 {source}: خطای اتصال (تلاش {attempt}/{retries})")
        except Exception as e:
            print(f"    ❌ {source}: {e}")
        if attempt < retries:
            time.sleep(2 ** attempt)
    return []


def _parse_entry(entry, source: str, dedicated: bool) -> dict | None:
    link = getattr(entry, "link", "").strip()
    if not link:
        return None

    title   = _clean_html(getattr(entry, "title",   "")).strip() or "بدون عنوان"
    summary = _clean_html(getattr(entry, "summary",  "") or getattr(entry, "description", "")).strip()
    if len(summary) > 500:
        summary = summary[:500] + "..."

    published = getattr(entry, "published", "") or getattr(entry, "updated", "")

    return {
        "title":     title,
        "link":      link,
        "summary":   summary,
        "source":    source,
        "published": published,
        "dedicated": dedicated,
    }


def collect_all_feeds() -> list:
    """جمع‌آوری از همه ۱۱ فید — نقطه ورود اصلی"""
    all_articles = []
    print(f"📡 جمع‌آوری از {len(RSS_FEEDS)} منبع...")
    print("-" * 50)
    for f in RSS_FEEDS:
        print(f"  🔍 {f['source']}:")
        entries = _fetch(f["url"], f["source"])
        for e in entries:
            art = _parse_entry(e, f["source"], f["dedicated"])
            if art:
                all_articles.append(art)
        time.sleep(1)
    print("-" * 50)
    print(f"📊 جمع کل: {len(all_articles)} خبر")
    return all_articles
