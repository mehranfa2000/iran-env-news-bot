"""
main.py — v4.0
ارکستراتور اصلی ایجنت هوشمند محیط‌زیست
جریان ۸ مرحله‌ای:
  ۱. اعتبارسنجی تنظیمات
  ۲. بارگذاری اخبار قبلی
  ۳. جمع‌آوری موازی از ۱۴ فید
  ۴. فیلتر ۴ لایه
  ۵. تحلیل هوش مصنوعی (خلاصه + بحرانی)
  ۶. ساخت NewsItem و ذخیره‌سازی
  ۷. ارسال به تلگرام و بله
  ۸. ذخیره آمار و commit
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timezone

from src.config import validate_config, MAX_NEWS_PER_RUN
from src.collector import collect_all_feeds
from src.filter import filter_news
from src.analyzer import analyze_news
from src.sender import send_news
from src.agent import (
    NewsItem,
    StorageManager,
    RunStats,
    RunStatsManager,
)

logger = logging.getLogger("main")


def run_agent() -> int:
    """
    اجرای کامل ایجنت.
    خروجی: کد خروج (0=موفق، 1=خطای جدی)
    """
    start_time = time.time()
    run_id = str(uuid.uuid4())[:8]

    stats = RunStats(
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info("=" * 60)
    logger.info("🚀 ایجنت محیط‌زیست v4.0 — شروع اجرا [%s]", run_id)
    logger.info("=" * 60)

    # ── مرحله ۱: اعتبارسنجی ──────────────────────────────────
    logger.info("⚙️  مرحله ۱/۸: اعتبارسنجی تنظیمات")
    if not validate_config():
        logger.critical("❌ تنظیمات ناقص است — ایجنت متوقف شد")
        return 1

    # ── مرحله ۲: بارگذاری ذخیره‌سازی ─────────────────────────
    logger.info("📂 مرحله ۲/۸: بارگذاری اخبار قبلی")
    storage = StorageManager()
    known_uids = storage.known_uids
    logger.info("   %d خبر قبلی در حافظه", len(known_uids))

    # ── مرحله ۳: جمع‌آوری ─────────────────────────────────────
    logger.info("📡 مرحله ۳/۸: جمع‌آوری از ۱۴ فید RSS")
    raw_items = collect_all_feeds()
    stats.raw_collected = len(raw_items)
    stats.feeds_fetched = len(set(i.source for i in raw_items))
    logger.info("   %d خبر خام از %d منبع", stats.raw_collected, stats.feeds_fetched)

    if not raw_items:
        logger.warning("⚠️ هیچ خبری دریافت نشد — پایان اجرا")
        _finish(stats, start_time, storage)
        return 0

    # ── مرحله ۴: فیلتر ───────────────────────────────────────
    logger.info("🔍 مرحله ۴/۸: فیلتر ۴ لایه")
    filtered_items = filter_news(raw_items, known_uids)
    stats.after_filter = len(filtered_items)
    stats.critical_count = sum(1 for i in filtered_items if i.critical)
    logger.info(
        "   %d خبر محیط‌زیستی (%d بحرانی)",
        stats.after_filter, stats.critical_count,
    )

    if not filtered_items:
        logger.info("ℹ️ خبر جدید محیط‌زیستی یافت نشد")
        _finish(stats, start_time, storage)
        return 0

    # محدود کردن به MAX_NEWS_PER_RUN (جدیدترین اول)
    new_items_to_send = filtered_items[:MAX_NEWS_PER_RUN]
    logger.info(
        "   ارسال %d خبر (از %d فیلترشده)",
        len(new_items_to_send), len(filtered_items),
    )

    # ── مرحله ۵: تحلیل AI ────────────────────────────────────
    logger.info("🤖 مرحله ۵/۸: تحلیل هوش مصنوعی")
    ai_results = analyze_news(new_items_to_send)
    stats.ai_analyzed  = sum(1 for r in ai_results.values() if r.pr_analysis)
    stats.ai_summarized = sum(1 for r in ai_results.values() if not r.pr_analysis)
    logger.info(
        "   %d تحلیل کامل + %d خلاصه‌سازی",
        stats.ai_analyzed, stats.ai_summarized,
    )

    # ── مرحله ۶: ساخت و ذخیره NewsItem ───────────────────────
    logger.info("💾 مرحله ۶/۸: ساخت و ذخیره اخبار")
    news_items: list[NewsItem] = []
    for fi in new_items_to_send:
        ai_res = ai_results.get(fi.uid)
        ni = NewsItem.from_filtered(fi, ai_res)
        news_items.append(ni)

    added_count = storage.add_items(news_items)
    stats.new_items = added_count
    logger.info("   %d خبر جدید ذخیره شد", added_count)

    # ── مرحله ۷: ارسال ───────────────────────────────────────
    logger.info("📤 مرحله ۷/۸: ارسال به تلگرام و بله")

    # فقط خبرهایی که واقعاً جدید بودند
    items_to_send = [
        fi for fi in new_items_to_send
        if fi.uid in {ni.uid for ni in news_items}
    ]

    send_results = send_news(items_to_send, ai_results)

    # به‌روزرسانی وضعیت ارسال در storage
    for sr in send_results:
        storage.update_send_status(sr.uid, sr.telegram_ok, sr.bale_ok)

    stats.sent_telegram = sum(1 for r in send_results if r.telegram_ok)
    stats.sent_bale     = sum(1 for r in send_results if r.bale_ok)
    logger.info(
        "   تلگرام: %d/%d ✅ | بله: %d/%d ✅",
        stats.sent_telegram, len(send_results),
        stats.sent_bale, len(send_results),
    )

    # ── مرحله ۸: ذخیره نهایی ─────────────────────────────────
    logger.info("💽 مرحله ۸/۸: ذخیره‌سازی نهایی")
    _finish(stats, start_time, storage)

    logger.info("=" * 60)
    logger.info("✅ ایجنت با موفقیت پایان یافت [%s] | ⏱ %.1f ثانیه", run_id, stats.duration_seconds)
    logger.info("=" * 60)
    return 0


def _finish(stats: RunStats, start_time: float, storage: StorageManager) -> None:
    """ذخیره نهایی داده‌ها و آمار"""
    stats.finished_at     = datetime.now(timezone.utc).isoformat()
    stats.duration_seconds = round(time.time() - start_time, 2)

    try:
        storage.save()
    except Exception as exc:
        logger.error("❌ خطا در ذخیره news.json: %s", exc)
        stats.errors.append(f"storage_save: {exc}")

    try:
        RunStatsManager().save_run(stats)
    except Exception as exc:
        logger.error("❌ خطا در ذخیره run_stats.json: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sys.exit(run_agent())
