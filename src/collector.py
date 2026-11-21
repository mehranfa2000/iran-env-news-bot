# ============================================================
# موتور جمع‌آوری اخبار از ۱۱ منبع خبری معتبر ایران
# با قابلیت timeout، retry و User-Agent واقعی
# ============================================================

import feedparser
import requests
import time

# هدر مرورگر واقعی برای جلوگیری از بلاک شدن
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ============================================================
# لیست کامل ۱۱ منبع خبری اختصاصی محیط زیست ایران
# ============================================================
SOURCES = [
    {
        "name": "ایرنا",
        "name_en": "IRNA",
        "url": "https://www.irna.ir/rss/tp/32",
        "dedicated": True   # فید اختصاصی محیط زیست
    },
    {
        "name": "مهر",
        "name_en": "Mehr",
        "url": "https://www.mehrnews.com/rss/tp/64",
        "dedicated": True
    },
    {
        "name": "همشهری",
        "name_en": "Hamshahri",
        "url": "https://www.hamshahrionline.ir/rss/tp/584",
        "dedicated": True
    },
    {
        "name": "خبرآنلاین",
        "name_en": "KhabarOnline",
        "url": "https://www.khabaronline.ir/rss/tp/44",
        "dedicated": True
    },
    {
        "name": "ایمنا",
        "name_en": "IMNA",
        "url": "https://www.imna.ir/rss/tp/153",
        "dedicated": True
    },
    {
        "name": "باشگاه خبرنگاران",
        "name_en": "YJC",
        "url": "https://www.yjc.ir/fa/rss/5/74",
        "dedicated": True
    },
    {
        "name": "اطلاعات",
        "name_en": "Ettelaat",
        "url": "https://www.ettelaat.com/rss/tp/65",
        "dedicated": True
    },
    {
        "name": "صدا و سیما",
        "name_en": "IRIBNews",
        "url": "https://www.iribnews.ir/fa/rss/7/39",
        "dedicated": True
    },
    {
        "name": "صدا و سیما - آب و انرژی",
        "name_en": "IRIBNews-Energy",
        "url": "https://www.iribnews.ir/fa/rss/6/8",
        "dedicated": True
    },
    {
        "name": "سلامت نیوز",
        "name_en": "SalamatNews",
        "url": "https://www.salamatnews.com/rss/tp/11",
        "dedicated": True
    },
    {
        "name": "ایسنا",
        "name_en": "ISNA",
        "url": "https://www.isna.ir/rss",
        "dedicated": False  # فید عمومی - نیاز به فیلتر کلیدواژه دارد
    }
]

def fetch_feed_with_retry(url, max_retries=3, timeout=15):
    """دریافت فید با قابلیت تلاش مجدد"""
    for attempt in range(max_retries):
        try:
            # تلاش اول با feedparser مستقیم
            feed = feedparser.parse(
                url,
                request_headers=HEADERS,
                agent=HEADERS["User-Agent"]
            )
            if feed.entries:
                return feed
            
            # اگر feedparser خالی برگشت، با requests امتحان کن
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            return feed

        except Exception as e:
            print(f"  ⚠️ تلاش {attempt + 1}/{max_retries} ناموفق: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)  # ۲ ثانیه صبر قبل از تلاش بعدی
    return None

def clean_text(text):
    """پاکسازی متن از تگ‌های HTML"""
    if not text:
        return ""
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()

def fetch_news():
    """جمع‌آوری اخبار از تمام منابع"""
    all_news = []
    
    print(f"\n📡 شروع دریافت اخبار از {len(SOURCES)} منبع خبری...\n")
    
    for source in SOURCES:
        print(f"  🔄 {source['name']} ({source['url'][:50]}...)")
        
        feed = fetch_feed_with_retry(source["url"])
        
        if not feed or not feed.entries:
            print(f"  ❌ دریافت نشد یا خالی بود: {source['name']}")
            continue
        
        count = 0
        for entry in feed.entries:
            title   = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", entry.get("description", "")))
            link    = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            
            if not title or not link:
                continue
            
            news_item = {
                "title":     title,
                "link":      link,
                "summary":   summary[:500],
                "source":    source["name_en"],
                "source_fa": source["name"],
                "published": published,
                "dedicated": source["dedicated"]
            }
            all_news.append(news_item)
            count += 1
        
        print(f"  ✅ {count} خبر از {source['name']} دریافت شد.")
        time.sleep(0.5)  # احترام به سرور منبع
    
    print(f"\n📊 مجموع: {len(all_news)} خبر از تمام منابع دریافت شد.\n")
    return all_news
