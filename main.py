# ============================================================
# مرکز فرماندهی - سامانه ملی پایش اخبار محیط زیست ایران
# ذخیره اخبار در فایل JSON با تاریخ شمسی
# ============================================================

import sys
import json
import os
from src.collector import fetch_news
from src.filter    import filter_and_categorize
from src.sender    import send_to_telegram, send_to_bale, format_message
from src.config    import Config
from src.utils     import now_shamsi, to_shamsi, format_shamsi_full
import time

NEWS_FILE     = "data/news.json"
MAX_STORED    = 500  # حداکثر اخبار ذخیره شده

def load_existing_news():
    if not os.path.exists(NEWS_FILE):
        os.makedirs("data", exist_ok=True)
        return []
    try:
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_news(news_list):
    os.makedirs("data", exist_ok=True)
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

def is_duplicate(link, existing_news):
    return any(item.get("link") == link for item in existing_news)

def main():
    print("=" * 55)
    print("🌿 سامانه ملی پایش اخبار محیط زیست ایران")
    print(f"📅 {format_shamsi_full()} | {now_shamsi()}")
    print("=" * 55)

    # ۱. بارگذاری اخبار قبلی
    existing_news = load_existing_news()
    print(f"\n📂 {len(existing_news)} خبر قبلی در پایگاه داده موجود است.")

    # ۲. جمع‌آوری
    raw_news = fetch_news()
    if not raw_news:
        print("❌ هیچ خبری دریافت نشد.")
        sys.exit(0)

    # ۳. پردازش
    sent_count      = 0
    duplicate_count = 0
    rejected_count  = 0
    new_news_list   = []

    print(f"\n🔍 شروع فیلتر و پردازش {len(raw_news)} خبر...\n")

    for item in raw_news:
        if sent_count >= Config.MAX_NEWS_PER_RUN:
            print(f"\n⚠️ به حد مجاز {Config.MAX_NEWS_PER_RUN} خبر رسیدیم.")
            break

        filtered = filter_and_categorize(item)
        if not filtered:
            rejected_count += 1
            continue

        if is_duplicate(filtered["link"], existing_news + new_news_list):
            duplicate_count += 1
            continue

        print(f"  ✅ [{filtered['emoji']} {filtered['category_fa']}] {filtered['title'][:55]}...")

        message = format_message(filtered, Config.CHANNEL_USERNAME)

        tg_ok   = send_to_telegram(Config.TG_TOKEN, Config.TG_CHAT_ID, message)
        bale_ok = send_to_bale(Config.BALE_TOKEN, Config.BALE_CHAT_ID, message)

        print(f"     📨 تلگرام: {'✅' if tg_ok else '❌'}  |  📱 بله: {'✅' if bale_ok else '❌'}")

        if tg_ok or bale_ok:
            # ذخیره تاریخ شمسی
            filtered["timestamp"]        = now_shamsi()
            filtered["timestamp_shamsi"] = now_shamsi("%Y/%m/%d %H:%M")
            filtered["date_shamsi"]      = now_shamsi("%Y/%m/%d")
            filtered["pub_shamsi"]       = to_shamsi(filtered.get("published", ""))
            new_news_list.append(filtered)
            sent_count += 1

        time.sleep(Config.DELAY_BETWEEN_SENDS)

    # ۴. ذخیره
    if new_news_list:
        combined = new_news_list + existing_news
        combined = combined[:MAX_STORED]
        save_news(combined)
        print(f"\n💾 {len(new_news_list)} خبر جدید ذخیره شد. (مجموع: {len(combined)})")

    # ۵. گزارش نهایی
    print("\n" + "=" * 55)
    print("📊 گزارش اجرا:")
    print(f"  🟢 ارسال شد:   {sent_count} خبر")
    print(f"  🔵 تکراری:     {duplicate_count} خبر")
    print(f"  🔴 نامرتبط:    {rejected_count} خبر")
    print(f"  📥 کل دریافتی: {len(raw_news)} خبر")
    print("=" * 55)

if __name__ == "__main__":
    main()
