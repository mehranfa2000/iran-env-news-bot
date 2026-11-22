# ============================================================
#  src/collector.py — جمع‌آوری اخبار از ۱۱ فید RSS
#  نسخه: 2.0 | آذر ۱۴۰۵
#  استانداردهای 2026: User-Agent، retry، timeout
# ============================================================

import time
import feedparser
import requests
from bs4 import BeautifulSoup

# ── لیست منابع RSS تأییدشده ──────────────────────────────────
RSS_FEEDS = [
    {
        "url":    "https://www.irna.ir/rss/tp/32",
        "source": "ایرنا",
        "dedicated": True,
    },
    {
        "url":    "https://www.mehrnews.com/rss/tp/64",
        "source": "مهر",
        "dedicated": True,
    },
    {
        "url":    "https://www.hamshahrionline.ir/rss/tp/584",
        "source": "همشهری",
        "dedicated": True,
    },
    {
        "url":    "https://www.khabaronline.ir/rss/tp/44",
        "source": "خبرآنلاین",
        "dedicated": True,
    },
    {
        "url":    "https://www.imna.ir/rss/tp/153",
        "source": "ایمنا",
        "dedicated": True,
    },
    {
        "url":    "https://www.yjc.ir/fa/rss/5/74",
        "source": "باشگاه خبرنگاران",
        "dedicated": True,
    },
    {
        "url":    "https://www.ettelaat.com/rss/tp/65",
        "source": "اطلاعات",
        "dedicated": True,
    },
    {
        "url":    "https://www.iribnews.ir/fa/rss/7/39",
        "source": "صدا و سیما",
        "dedicated": True,
    },
    {
        "url":    "https://www.iribnews.ir/fa/rss/6/8",
        "source": "صدا و سیما — آب و انرژی",
        "dedicated": True,
    },
    {
        "url":    "https://www.salamatnews.com/rss/tp/11",
        "source": "سلامت نیوز",
        "dedicated": True,
    },
    {
        "url":    "https://www.isna.ir/rss",
        "source": "ایسنا",
        "dedicated": False,   # فید عمومی — نیاز به فیلتر سخت‌تر دارد
    },
]

# ── User-Agent های مختلف برای جلوگیری از بلاک شدن ────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",

    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
    "Gecko/20100101 Firefox/132.0",
]

# ── شمارنده برای چرخش User-Agent ─────────────────────────────
_ua_index = 0


def _get_next_ua() -> str:
    """هر بار یک User-Agent متفاوت برمی‌گرداند"""
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


def _clean_html(raw: str) -> str:
    """
    حذف تگ‌های HTML از متن
    فقط اگر متن واقعاً HTML باشد (شامل < و >)
    """
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        try:
            return BeautifulSoup(raw, "html.parser").get_text(
                separator=" ", strip=True
            )
        except Exception:
            return raw
    return raw.strip()


def fetch_feed_with_retry(
    url: str,
    source: str,
    max_retries: int = 3,
    timeout: int = 20,
) -> list:
    """
    دریافت فید RSS با retry و exponential backoff

    Returns:
        لیست مقالات خام از فید
    """
    headers = {
        "User-Agent": _get_next_ua(),
        "Accept": (
            "application/rss+xml, application/xml, "
            "application/atom+xml, text/xml, */*"
        ),
        "Accept-Language": "fa,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    for attempt in range(1, max_retries + 1):
        try:
            # دریافت محتوای فید با requests (کنترل بهتر)
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

            # اگر 403 بود — این سرور GitHub را بلاک کرده، تلاش مجدد بی‌فایده است
            if response.status_code == 403:
                print(f"    ⛔ {source}: دسترسی رد شد (403) — رد می‌شود")
                return []

            # اگر کد وضعیت موفق نبود
            if response.status_code != 200:
                print(
                    f"    ⚠️  {source}: کد {response.status_code} "
                    f"(تلاش {attempt}/{max_retries})"
                )
                if attempt < max_retries:
                    wait = 2 ** attempt      # 2، 4، 8 ثانیه
                    time.sleep(wait)
                continue

            # parse کردن فید
            feed = feedparser.parse(response.content)

            if not feed.entries:
                print(f"    ⚠️  {source}: فید خالی است")
                return []

            print(f"    ✅ {source}: {len(feed.entries)} مقاله دریافت شد")
            return feed.entries

        except requests.exceptions.Timeout:
            print(
                f"    ⏱️  {source}: timeout "
                f"(تلاش {attempt}/{max_retries})"
            )
        except requests.exceptions.ConnectionError:
            print(
                f"    🔌 {source}: خطای اتصال "
                f"(تلاش {attempt}/{max_retries})"
            )
        except Exception as e:
            print(
                f"    ❌ {source}: خطای غیرمنتظره: {e} "
                f"(تلاش {attempt}/{max_retries})"
            )

        if attempt < max_retries:
            wait = 2 ** attempt
            print(f"    ⏳ {wait} ثانیه صبر می‌کنیم...")
            time.sleep(wait)

    print(f"    ❌ {source}: همه {max_retries} تلاش ناموفق بود")
    return []


def parse_entry(entry, source: str, dedicated: bool) -> dict | None:
    """
    تبدیل یک entry از feedparser به دیکشنری استاندارد

    Returns:
        دیکشنری خبر یا None اگر لینک نداشت
    """
    # لینک — کلید اصلی deduplication
    link = ""
    if hasattr(entry, "link") and entry.link:
        link = entry.link.strip()
    if not link:
        return None

    # عنوان
    title = ""
    if hasattr(entry, "title") and entry.title:
        title = _clean_html(entry.title).strip()
    if not title:
        title = "بدون عنوان"

    # خلاصه / توضیح
    summary = ""
    if hasattr(entry, "summary") and entry.summary:
        summary = _clean_html(entry.summary).strip()
    elif hasattr(entry, "description") and entry.description:
        summary = _clean_html(entry.description).strip()

    # محدود کردن خلاصه به ۵۰۰ کاراکتر
    if len(summary) > 500:
        summary = summary[:500] + "..."

    # تاریخ انتشار
    published = ""
    if hasattr(entry, "published") and entry.published:
        published = entry.published
    elif hasattr(entry, "updated") and entry.updated:
        published = entry.updated

    return {
        "title":     title,
        "link":      link,
        "summary":   summary,
        "source":    source,
        "published": published,
        "dedicated": dedicated,   # آیا فید اختصاصی محیط‌زیست است؟
    }


def collect_all_feeds() -> list:
    """
    جمع‌آوری اخبار از همه ۱۱ فید RSS

    Returns:
        لیست همه مقالات خام (قبل از فیلتر)
    """
    all_articles = []

    print(f"📡 شروع جمع‌آوری از {len(RSS_FEEDS)} منبع خبری...")
    print("-" * 50)

    for feed_info in RSS_FEEDS:
        url       = feed_info["url"]
        source    = feed_info["source"]
        dedicated = feed_info["dedicated"]

        print(f"  🔍 {source}:")

        # دریافت entries از فید
        entries = fetch_feed_with_retry(url, source)

        if not entries:
            continue

        # تبدیل هر entry به دیکشنری استاندارد
        count = 0
        for entry in entries:
            article = parse_entry(entry, source, dedicated)
            if article:
                all_articles.append(article)
                count += 1

        # کمی تأخیر بین درخواست‌ها (احترام به سرورها)
        time.sleep(1)

    print("-" * 50)
    print(f"📊 جمع کل قبل از فیلتر: {len(all_articles)} خبر")

    return all_articles
