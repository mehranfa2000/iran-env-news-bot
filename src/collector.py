# ============================================================
# موتور جمع‌آوری اخبار از ۱۱ منبع خبری معتبر ایران
# نسخه رفع اشکال شده - با مدیریت کامل خطا
# ============================================================

import feedparser
import requests
import time
import re

# هدر مرورگر واقعی برای جلوگیری از بلاک شدن
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "fa,en;q=0.9",
}

# ============================================================
# لیست کامل ۱۱ منبع خبری اختصاصی محیط زیست ایران
# ============================================================
SOURCES = [
    {
        "name":      "ایرنا",
        "name_en":   "IRNA",
        "url":       "https://www.irna.ir/rss/tp/32",
        "dedicated": True
    },
    {
        "name":      "مهر",
        "name_en":   "Mehr",
        "url":       "https://www.mehrnews.com/rss/tp/64",
        "dedicated": True
    },
    {
        "name":      "همشهری",
        "name_en":   "Hamshahri",
        "url":       "https://www.hamshahrionline.ir/rss/tp/584",
        "dedicated": True
    },
    {
        "name":      "خبرآنلاین",
        "name_en":   "KhabarOnline",
        "url":       "https://www.khabaronline.ir/rss/tp/44",
        "dedicated": True
    },
    {
        "name":      "ایمنا",
        "name_en":   "IMNA",
        "url":       "https://www.imna.ir/rss/tp/153",
        "dedicated": True
    },
    {
        "name":      "اطلاعات",
        "name_en":   "Ettelaat",
        "url":       "https://www.ettelaat.com/rss/tp/65",
        "dedicated": True
    },
    {
        "name":      "صدا و سیما",
        "name_en":   "IRIBNews",
        "url":       "https://www.iribnews.ir/fa/rss/7/39",
        "dedicated": True
    },
    {
        "name":      "صدا و سیما - آب و انرژی",
        "name_en":   "IRIBNews-Energy",
        "url":       "https://www.iribnews.ir/fa/rss/6/8",
        "dedicated": True
    },
    {
        "name":      "سلامت نیوز",
        "name_en":   "SalamatNews",
        "url":       "https://www.salamatnews.com/rss/tp/11",
        "dedicated": True
    },
    {
        "name":      "باشگاه خبرنگاران",
        "name_en":   "YJC",
        "url":       "https://www.yjc.ir/fa/rss/5/74",
        "dedicated": True
    },
    {
        "name":      "ایسنا",
        "name_en":   "ISNA",
        "url":       "https://www.isna.ir/rss",
        "dedicated": False  # فید عمومی - نیاز به فیلتر کلیدواژه دارد
    }
]

# ============================================================
# پاکسازی متن از تگ‌های HTML - نسخه رفع اشکال شده
# ============================================================
def clean_text(text):
    """پاکسازی متن از تگ‌های HTML بدون خطای BeautifulSoup"""
    if not text:
        return ""

    text = str(text).strip()

    # اگر متن خالی یا خیلی کوتاه است
    if len(text) < 3:
        return text

    # اگر تگ HTML دارد، با regex پاک کن
    if "<" in text and ">" in text:
        try:
            # روش اول: با BeautifulSoup
            from bs4 import BeautifulSoup
            # حتماً به صورت string کامل پاس بده نه فایل‌نیم
            soup = BeautifulSoup(text, "html.parser")
            cleaned = soup.get_text(separator=" ")
            cleaned = " ".join(cleaned.split())  # فاصله‌های اضافی را پاک کن
            return cleaned.strip()
        except Exception:
            # روش دوم: با regex
            cleaned = re.sub(r"<[^>]+>", " ", text)
            cleaned = " ".join(cleaned.split())
            return cleaned.strip()

    # اگر HTML ندارد، همان متن را برگردان
    return text

# ============================================================
# دریافت فید با قابلیت تلاش مجدد
# ============================================================
def fetch_feed_with_retry(source, max_retries=3, timeout=20):
    """دریافت فید RSS با چندین روش و تلاش مجدد"""
    url  = source["url"]
    name = source["name"]

    for attempt in range(max_retries):
        try:
            # ===== روش اول: feedparser مستقیم =====
            feed = feedparser.parse(
                url,
                request_headers=HEADERS,
                agent=HEADERS["User-Agent"]
            )

            # اگر خطای جدی نداشت و خبر داشت
            if feed.entries and not (feed.bozo and not feed.entries):
                return feed

            # ===== روش دوم: requests + feedparser =====
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True
            )
            response.raise_for_status()

            # بررسی نوع محتوا
            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type and "xml" not in content_type:
                print(f"  ⚠️ {name}: پاسخ HTML بود نه RSS")
                return None

            feed = feedparser.parse(response.content)

            if feed.entries:
                return feed
            else:
                print(f"  ⚠️ {name}: فید خالی بود (تلاش {attempt+1}/{max_retries})")

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            print(f"  ⚠️ تلاش {attempt+1}/{max_retries} ناموفق: {status} - {name}")
            if status == 403:
                # 403 یعنی دسترسی ممنوع - تلاش بیشتر فایده ندارد
                print(f"  🚫 {name}: دسترسی ممنوع (403) - رد می‌شود.")
                return None

        except requests.exceptions.Timeout:
            print(f"  ⏱️ تلاش {attempt+1}/{max_retries}: timeout - {name}")

        except requests.exceptions.ConnectionError:
            print(f"  🔌 تلاش {attempt+1}/{max_retries}: خطای اتصال - {name}")

        except Exception as e:
            print(f"  ❌ تلاش {attempt+1}/{max_retries} ناموفق: {e}")

        # صبر قبل از تلاش بعدی
        if attempt < max_retries - 1:
            time.sleep(2)

    return None

# ============================================================
# استخراج اطلاعات یک آیتم از فید
# ============================================================
def parse_entry(entry, source):
    """استخراج و پاکسازی اطلاعات یک خبر از فید"""
    try:
        # عنوان
        title = clean_text(entry.get("title", ""))

        # خلاصه (چندین فیلد احتمالی)
        summary_raw = (
            entry.get("summary", "") or
            entry.get("description", "") or
            entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
        )
        summary = clean_text(str(summary_raw))

        # لینک
        link = entry.get("link", "").strip()

        # زمان انتشار
        published = (
            entry.get("published", "") or
            entry.get("updated", "") or
            entry.get("dc_date", "")
        )

        # اعتبارسنجی
        if not title or not link:
            return None

        # لینک باید با http شروع شود
        if not link.startswith("http"):
            return None

        return {
            "title":     title[:300],
            "link":      link,
            "summary":   summary[:600],
            "source":    source["name_en"],
            "source_fa": source["name"],
            "published": str(published)[:30],
            "dedicated": source["dedicated"]
        }

    except Exception as e:
        print(f"    ⚠️ خطا در پردازش آیتم: {e}")
        return None

# ============================================================
# تابع اصلی جمع‌آوری اخبار
# ============================================================
def fetch_news():
    """جمع‌آوری اخبار از تمام منابع"""
    all_news = []
    success_count = 0
    fail_count    = 0

    print(f"\n📡 شروع دریافت اخبار از {len(SOURCES)} منبع خبری...\n")

    for source in SOURCES:
        name = source["name"]
        url  = source["url"]
        print(f"  🔄 {name} ({url[:45]}...)")

        # دریافت فید
        feed = fetch_feed_with_retry(source)

        if not feed or not feed.entries:
            print(f"  ❌ دریافت نشد یا خالی بود: {name}")
            fail_count += 1
            # تأخیر کوتاه قبل از منبع بعدی
            time.sleep(1)
            continue

        # پردازش آیتم‌ها
        source_news = []
        for entry in feed.entries:
            item = parse_entry(entry, source)
            if item:
                source_news.append(item)

        count = len(source_news)
        all_news.extend(source_news)
        success_count += 1

        print(f"  ✅ {count} خبر از {name} دریافت شد.")

        # تأخیر کوتاه برای احترام به سرور منبع
        time.sleep(0.8)

    # گزارش نهایی جمع‌آوری
    print(f"\n{'─'*45}")
    print(f"📊 نتیجه جمع‌آوری:")
    print(f"   ✅ منابع موفق:   {success_count}")
    print(f"   ❌ منابع ناموفق: {fail_count}")
    print(f"   📰 کل اخبار:    {len(all_news)}")
    print(f"{'─'*45}\n")

    return all_news
