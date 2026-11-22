# ============================================================
#  main.py — هماهنگ‌کننده اصلی + تحلیل AI
#  نسخه 3.0 | آذر ۱۴۰۵
# ============================================================

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

from src.collector import collect_all_feeds
from src.filter    import filter_news
from src.sender    import send_to_telegram, send_to_bale
from src.analyzer  import analyze_batch
from src.utils     import parse_rss_date, now_utc_iso
from src.config    import (
    MAX_NEWS_PER_RUN, DELAY_BETWEEN_SENDS,
    MAX_STORED_NEWS, AI_ENABLED,
)

NEWS_FILE = Path("data/news.json")


def load_news() -> list:
    if not NEWS_FILE.exists():
        print("📂 news.json وجود ندارد — از صفر شروع می‌شود")
        return []
    try:
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            print(f"📂 {len(data)} خبر قبلی بارگذاری شد")
            return data
        return []
    except Exception as e:
        print(f"⚠️  خطا: {e}")
        return []


def save_news(news_list: list) -> bool:
    try:
        NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
        trimmed = news_list[-MAX_STORED_NEWS:]
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
        print(f"💾 {len(trimmed)} خبر ذخیره شد")
        return True
    except Exception as e:
        print(f"❌ خطا در ذخیره: {e}")
        return False


def main():
    t0 = time.time()
    print("=" * 60)
    print("🌿 سامانه پایش اخبار محیط زیست — نسخه ۳.۰")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"🧠 AI: {'✅ فعال' if AI_ENABLED else '❌ غیرفعال'}")
    print("=" * 60)

    # ── ۱. بارگذاری ──────────────────────────────────────────
    existing   = load_news()
    seen_links = {a.get("link", "").strip() for a in existing if a.get("link")}

    # ── ۲. جمع‌آوری ─────────────────────────────────────────
    print("\n📌 مرحله ۱: جمع‌آوری...")
    try:
        raw = collect_all_feeds()
    except Exception as e:
        print(f"❌ جمع‌آوری ناموفق: {e}")
        save_news(existing)
        sys.exit(0)

    # ── ۳. فیلتر ────────────────────────────────────────────
    print("\n📌 مرحله ۲: فیلتر محیط‌زیستی...")
    try:
        filtered = filter_news(raw)
        print(f"✅ {len(filtered)} خبر محیط‌زیستی")
    except Exception as e:
        print(f"❌ فیلتر ناموفق: {e}")
        save_news(existing)
        sys.exit(0)

    # ── ۴. حذف تکراری ───────────────────────────────────────
    print("\n📌 مرحله ۳: حذف تکراری...")
    new_items = [
        a for a in filtered
        if a.get("link", "").strip() and a["link"].strip() not in seen_links
    ]
    print(f"🆕 {len(new_items)} خبر جدید")

    if len(new_items) > MAX_NEWS_PER_RUN:
        new_items = new_items[:MAX_NEWS_PER_RUN]
        print(f"⚡ محدود به {MAX_NEWS_PER_RUN}")

    if not new_items:
        print("ℹ️  خبر جدیدی نیست")
        save_news(existing)
        return

    # ── ۵. تاریخ شمسی ───────────────────────────────────────
    for art in new_items:
        art["date_shamsi"] = parse_rss_date(art.get("published", ""))

    # ── ۶. تحلیل AI 🧠 ──────────────────────────────────────
    print("\n📌 مرحله ۴: تحلیل AI...")
    new_items = analyze_batch(new_items)

    # ── ۷. ارسال ────────────────────────────────────────────
    print(f"\n📌 مرحله ۵: ارسال {len(new_items)} خبر...")
    sent = tg_fail = bale_fail = 0

    for i, art in enumerate(new_items, 1):
        print(f"\n  [{i}/{len(new_items)}] {art.get('title','')[:55]}...")

        tg_ok = bale_ok = False

        try:
            tg_ok = send_to_telegram(art)
            print(f"    تلگرام: {'✅' if tg_ok else '❌'}")
        except Exception as e:
            print(f"    تلگرام: ❌ {e}")
            tg_fail += 1

        time.sleep(DELAY_BETWEEN_SENDS)

        try:
            bale_ok = send_to_bale(art)
            print(f"    بله:     {'✅' if bale_ok else '❌'}")
        except Exception as e:
            print(f"    بله:     ❌ {e}")
            bale_fail += 1

        time.sleep(DELAY_BETWEEN_SENDS)

        art["sent_at"]     = now_utc_iso()
        art["telegram_ok"] = tg_ok
        art["bale_ok"]     = bale_ok

        existing.append(art)
        seen_links.add(art["link"].strip())

        if tg_ok or bale_ok:
            sent += 1

    # ── ۸. ذخیره ────────────────────────────────────────────
    print("\n📌 مرحله ۶: ذخیره...")
    ok = save_news(existing)

    # ── گزارش ───────────────────────────────────────────────
    elapsed = round(time.time() - t0, 1)
    print("\n" + "=" * 60)
    print("📊 گزارش نهایی:")
    print(f"   دریافتی:       {len(raw)}")
    print(f"   بعد از فیلتر:  {len(filtered)}")
    print(f"   جدید:          {len(new_items)}")
    print(f"   ارسال موفق:    {sent}")
    print(f"   خطای تلگرام:  {tg_fail}")
    print(f"   خطای بله:     {bale_fail}")
    print(f"   AI فعال:       {'بله' if AI_ENABLED else 'خیر'}")
    print(f"   زمان اجرا:    {elapsed}s")
    print("=" * 60)

    if not ok:
        sys.exit(1)
    print("✅ پایان موفق")


if __name__ == "__main__":
    main()
