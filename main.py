# ============================================================
# مرکز فرماندهی پروژه
# پایش هوشمند اخبار محیط زیست ایران - سطح ملی
# ============================================================

import sys
from src.collector  import fetch_news
from src.filter     import filter_and_categorize
from src.sender     import send_to_telegram, send_to_bale, format_message
from src.database   import Database
from src.config     import Config
import time

def main():
    print("=" * 50)
    print("🌿 پایش هوشمند اخبار محیط زیست ایران")
    print("=" * 50)

    # ۱. اتصال و آماده‌سازی دیتابیس
    print("\n🗄️ اتصال به پایگاه داده...")
    db = Database()
    db.setup()
    print("✅ پایگاه داده آماده است.")

    # ۲. جمع‌آوری اخبار از تمام منابع
    raw_news = fetch_news()

    if not raw_news:
        print("❌ هیچ خبری دریافت نشد. اجرا متوقف شد.")
        sys.exit(0)

    # ۳. فیلتر، دسته‌بندی و ارسال
    sent_count      = 0
    duplicate_count = 0
    rejected_count  = 0

    print(f"\n🔍 شروع فیلتر و پردازش {len(raw_news)} خبر...\n")

    for item in raw_news:
        # اگر به حد مجاز رسیدیم متوقف شو
        if sent_count >= Config.MAX_NEWS_PER_RUN:
            print(f"\n⚠️ به حد مجاز {Config.MAX_NEWS_PER_RUN} خبر رسیدیم.")
            break

        # لایه فیلتر
        filtered = filter_and_categorize(item)
        if not filtered:
            rejected_count += 1
            continue

        # بررسی تکراری بودن
        if db.is_duplicate(filtered["link"]):
            duplicate_count += 1
            continue

        print(f"  ✅ [{filtered['emoji']} {filtered['category_fa']}] {filtered['title'][:60]}...")

        # آماده‌سازی پیام
        message = format_message(filtered, Config.CHANNEL_USERNAME)

        # ارسال به تلگرام
        tg_ok = send_to_telegram(Config.TG_TOKEN, Config.TG_CHAT_ID, message)
        if tg_ok:
            print(f"     📨 تلگرام: ارسال شد ✅")
        else:
            print(f"     📨 تلگرام: ارسال ناموفق ❌")

        # ارسال به بله
        bale_ok = send_to_bale(Config.BALE_TOKEN, Config.BALE_CHAT_ID, message)
        if bale_ok:
            print(f"     📱 بله: ارسال شد ✅")
        else:
            print(f"     📱 بله: ارسال ناموفق ❌")

        # ذخیره در دیتابیس
        if tg_ok or bale_ok:
            db.add_news(filtered)
            sent_count += 1

        # تأخیر بین ارسال‌ها
        time.sleep(Config.DELAY_BETWEEN_SENDS)

    # ۴. گزارش نهایی
    print("\n" + "=" * 50)
    print("📊 گزارش اجرا:")
    print(f"  🟢 ارسال شد:   {sent_count} خبر")
    print(f"  🔵 تکراری:     {duplicate_count} خبر")
    print(f"  🔴 نامرتبط:    {rejected_count} خبر")
    print(f"  📥 کل دریافتی: {len(raw_news)} خبر")
    print("=" * 50)

if __name__ == "__main__":
    main()
