# ============================================================
#  main.py — سامانه هوشمند پایش اخبار محیط زیست ایران
#  نسخه: 2.0 | تاریخ: آذر ۱۴۰۵
#  استانداردهای 2026: JSON storage, dedup, Shamsi dates
# ============================================================

import json
import os
import time
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── ماژول‌های داخلی پروژه ──────────────────────────────────
from src.collector import collect_all_feeds
from src.filter    import filter_news
from src.sender    import send_to_telegram, send_to_bale
from src.config    import (
    MAX_NEWS_PER_RUN,
    DELAY_BETWEEN_SENDS,
)

# ── تنظیمات ──────────────────────────────────────────────────
NEWS_FILE   = Path("data/news.json")   # مسیر فایل ذخیره اخبار
MAX_STORED  = 500                       # حداکثر اخبار نگه‌داشته‌شده


# ════════════════════════════════════════════════════════════
#  توابع کمکی
# ════════════════════════════════════════════════════════════

def load_news() -> list:
    """
    بارگذاری اخبار قبلی از news.json
    اگر فایل وجود نداشت یا خراب بود، لیست خالی برمی‌گرداند.
    """
    if not NEWS_FILE.exists():
        print("📂 فایل news.json وجود ندارد — لیست خالی شروع می‌شود.")
        return []
    try:
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            print(f"📂 اخبار موجود بارگذاری شد: {len(data)} مورد")
            return data
        else:
            print("⚠️  ساختار news.json نامعتبر است — لیست خالی شروع می‌شود.")
            return []
    except json.JSONDecodeError as e:
        print(f"⚠️  خطا در خواندن news.json: {e} — لیست خالی شروع می‌شود.")
        return []
    except IOError as e:
        print(f"❌ خطای فایل: {e}")
        return []


def save_news(news_list: list) -> bool:
    """
    ذخیره اخبار در news.json
    فقط MAX_STORED مورد آخر نگه داشته می‌شود.
    مقدار True اگر موفق بود، False در صورت خطا.
    """
    try:
        NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)

        # فقط جدیدترین MAX_STORED خبر را نگه می‌داریم
        trimmed = news_list[-MAX_STORED:]

        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

        print(f"💾 news.json ذخیره شد — {len(trimmed)} خبر")
        return True

    except IOError as e:
        print(f"❌ خطا در ذخیره news.json: {e}")
        return False


def get_existing_links(news_list: list) -> set:
    """
    مجموعه لینک‌های موجود برای تشخیص تکراری‌ها
    """
    return {
        item.get("link", "").strip()
        for item in news_list
        if item.get("link", "").strip()
    }


def now_utc_iso() -> str:
    """زمان فعلی UTC به فرمت ISO 8601"""
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════
#  تابع اصلی
# ════════════════════════════════════════════════════════════

def main():
    start_time = time.time()
    print("=" * 60)
    print("🌿 سامانه پایش اخبار محیط زیست ایران")
    print(f"⏰ شروع: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)

    # ── مرحله ۱: بارگذاری اخبار قبلی ───────────────────────
    print("\n📌 مرحله ۱: بارگذاری اخبار قبلی...")
    existing_news  = load_news()
    existing_links = get_existing_links(existing_news)

    # ── مرحله ۲: جمع‌آوری از RSS فیدها ─────────────────────
    print("\n📌 مرحله ۲: جمع‌آوری از منابع خبری...")
    try:
        raw_articles = collect_all_feeds()
        print(f"📡 تعداد اخبار دریافتی از همه منابع: {len(raw_articles)}")
    except Exception as e:
        print(f"❌ خطا در جمع‌آوری اخبار: {e}")
        raw_articles = []

    if not raw_articles:
        print("⚠️  هیچ خبری دریافت نشد — اجرا پایان یافت.")
        save_news(existing_news)
        return

    # ── مرحله ۳: فیلتر کلیدواژه‌ای ۳ لایه ─────────────────
    print("\n📌 مرحله ۳: فیلتر محیط‌زیستی (۳ لایه)...")
    try:
        filtered_articles = filter_news(raw_articles)
        print(f"✅ اخبار محیط‌زیستی پس از فیلتر: {len(filtered_articles)}")
    except Exception as e:
        print(f"❌ خطا در فیلتر: {e}")
        save_news(existing_news)
        return

    # ── مرحله ۴: حذف اخبار تکراری ──────────────────────────
    print("\n📌 مرحله ۴: حذف اخبار تکراری...")
    new_articles = [
        a for a in filtered_articles
        if a.get("link", "").strip()
        and a["link"].strip() not in existing_links
    ]
    print(f"🆕 اخبار جدید (غیرتکراری): {len(new_articles)}")

    # محدود به MAX_NEWS_PER_RUN خبر در هر اجرا
    if len(new_articles) > MAX_NEWS_PER_RUN:
        print(f"⚡ محدود شد به {MAX_NEWS_PER_RUN} خبر در این اجرا")
        new_articles = new_articles[:MAX_NEWS_PER_RUN]

    if not new_articles:
        print("ℹ️  خبر جدیدی برای ارسال وجود ندارد.")
        save_news(existing_news)
        return

    # ── مرحله ۵: ارسال به کانال‌ها ──────────────────────────
    print(f"\n📌 مرحله ۵: ارسال {len(new_articles)} خبر به کانال‌ها...")
    print("-" * 40)

    sent_count      = 0
    tg_fail_count   = 0
    bale_fail_count = 0

    for i, article in enumerate(new_articles, 1):
        title = article.get("title", "بدون عنوان")[:60]
        print(f"\n  [{i}/{len(new_articles)}] {title}...")

        tg_ok   = False
        bale_ok = False

        # ارسال به تلگرام
        try:
            tg_ok = send_to_telegram(article)
            status = "✅" if tg_ok else "❌"
            print(f"    تلگرام: {status}")
        except Exception as e:
            print(f"    تلگرام: ❌ خطا — {e}")
            tg_fail_count += 1

        time.sleep(DELAY_BETWEEN_SENDS)

        # ارسال به بله
        try:
            bale_ok = send_to_bale(article)
            status = "✅" if bale_ok else "❌"
            print(f"    بله:     {status}")
        except Exception as e:
            print(f"    بله:     ❌ خطا — {e}")
            bale_fail_count += 1

        time.sleep(DELAY_BETWEEN_SENDS)

        # افزودن به لیست اخبار (حتی اگر ارسال ناموفق بود)
        # دلیل: از ارسال مکرر جلوگیری می‌کند
        article["sent_at"]      = now_utc_iso()
        article["telegram_ok"]  = tg_ok
        article["bale_ok"]      = bale_ok

        existing_news.append(article)
        existing_links.add(article["link"].strip())

        if tg_ok or bale_ok:
            sent_count += 1

    # ── مرحله ۶: ذخیره در news.json ─────────────────────────
    print(f"\n📌 مرحله ۶: ذخیره در news.json...")
    saved = save_news(existing_news)

    # ── گزارش نهایی ──────────────────────────────────────────
    elapsed = round(time.time() - start_time, 1)
    print("\n" + "=" * 60)
    print("📊 گزارش اجرا:")
    print(f"   • اخبار دریافتی از RSS:    {len(raw_articles)}")
    print(f"   • بعد از فیلتر محیط‌زیست:  {len(filtered_articles)}")
    print(f"   • اخبار جدید (غیرتکراری): {len(new_articles)}")
    print(f"   • ارسال موفق:              {sent_count}")
    print(f"   • خطای تلگرام:             {tg_fail_count}")
    print(f"   • خطای بله:                {bale_fail_count}")
    print(f"   • کل اخبار ذخیره‌شده:      {len(existing_news)}")
    print(f"   • ذخیره news.json:         {'✅' if saved else '❌'}")
    print(f"   • زمان اجرا:               {elapsed} ثانیه")
    print("=" * 60)
    print("✅ اجرا با موفقیت پایان یافت.")

    # اگر ذخیره موفق نبود، با exit code خطا خارج شو
    # تا GitHub Actions متوجه مشکل شود
    if not saved:
        sys.exit(1)


if __name__ == "__main__":
    main()
