import feedparser
import requests
from bs4 import BeautifulSoup

def fetch_news():
    # منابع خبری (RSS)
    sources = [
        {"name": "IRNA", "url": "https://www.irna.ir/rss/tp/11"}, # محیط زیست ایرنا
        {"name": "ISNA", "url": "https://www.isna.ir/rss/tp/26"}, # محیط زیست ایسنا
        {"name": "Fars", "url": "https://www.farsnews.ir/rss/environment"} # محیط زیست فارس
    ]
    
    all_news = []
    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                news_item = {
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.get("summary", ""),
                    "source": source["name"],
                    "published": entry.get("published", "")
                }
                all_news.append(news_item)
        except Exception as e:
            print(f"Error fetching from {source['name']}: {e}")
            
    return all_news
