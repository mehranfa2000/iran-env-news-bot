from src.collector import fetch_news
from src.filter import filter_and_categorize
from src.sender import send_to_telegram, send_to_bale, format_message
from src.database import Database
from src.config import Config

def start_bot():
    print("🚀 آغاز فعالیت بات محیط زیست...")
    db = Database()
    
    # ۱. جمع‌آوری اخبار
    raw_news = fetch_news()
    print(f"📥 تعداد {len(raw_news)} خبر دریافت شد.")

    for item in raw_news:
        # ۲. فیلتر و دسته‌بندی
        filtered_item = filter_and_categorize(item)
        
        if filtered_item:
            # ۳. بررسی تکراری نبودن
            if not db.is_duplicate(filtered_item['link']):
                print(f"✅ خبر تایید شد: {filtered_item['title']}")
                
                # ۴. آماده‌سازی پیام
                message = format_message(filtered_item)
                
                # ۵. ارسال به تلگرام و بله
                send_to_telegram(Config.TG_TOKEN, Config.TG_CHAT_ID, message)
                send_to_bale(Config.BALE_TOKEN, Config.BALE_CHAT_ID, message)
                
                # ۶. ذخیره در دیتابیس برای جلوگیری از تکرار
                db.add_news(filtered_item)
            else:
                print(f"⏭️ خبر تکراری بود: {filtered_item['title']}")

if __name__ == "__main__":
    start_bot()
