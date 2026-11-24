# main.py
"""
هماهنگ‌کننده اصلی سیستم — ۸ فاز
نسخه ۴.۰
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timezone

# تنظیم مسیر جستجو برای import
sys.path.insert(0, "src")

from agent import NewsItem, RunStats, RunStatsManager, StorageManager
from analyzer import NewsAnalyzer
from collector import AdaptiveFetcher
from config import (
    AI_MAX_PER_RUN,
    AI_SUMMARY_MAX_PER_RUN,
    MAX_NEWS_PER_RUN,
)
from filter import NewsFilter
from sender import NewsSender

logger = logging.getLogger("main")


def main() -> None:
    start_time = time.monotonic()
    run_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("🚀 شروع اجرا — run_id: %s", run_id)
    logger.info("=" * 60)

    stats = RunStats(run_id=run_id, started_at=started_at)
    storage = StorageManager()
    stats_mgr = RunStatsManager()

    # ── فاز ۱: جمع‌آوری ──
    logger.info("📡 فاز ۱: جمع‌آوری اخبار")
    fetcher = AdaptiveFetcher()
    raw_items = fetcher.fetch_all()
    stats.feeds_checked = 14
    stats.items_fetched = len(raw_items)

    # ── فاز ۲: حذف تکراری ──
    logger.info("🔎 فاز ۲: حذف تکراری")
    new_items = [i for i in raw_items if not storage.exists(i.uid)]
    logger.info("🆕 %d خبر جدید از %d کل", len(new_items), len(raw_items))

    # ── فاز ۳: فیلتر ──
    logger.info("🔍 فاز ۳: فیلتر محیط‌زیستی")
    news_filter = NewsFilter()
    filtered = news_filter.filter(new_items)
    stats.items_filtered = len(filtered)

    # ── فاز ۴: محدود کردن تعداد ──
    logger.info("📊 فاز ۴: انتخاب بهترین اخبار (حداکثر %d)", MAX_NEWS_PER_RUN)
    to_process = filtered[:MAX_NEWS_PER_RUN]

    # ── فاز ۵: ذخیره اولیه ──
    logger.info("💾 فاز ۵: ذخیره اولیه")
    for item in to_process:
        storage.add(item)
    storage.save()

    # ── فاز ۶: تحلیل AI ──
    logger.info("🤖 فاز ۶: تحلیل هوش مصنوعی")
    analyzer = NewsAnalyzer(
        max_critical=AI_MAX_PER_RUN,
        max_summary=AI_SUMMARY_MAX_PER_RUN,
    )
    analyzed = analyzer.analyze_batch(to_process)
    ai_count = sum(1 for i in analyzed if i.ai_summary)
    stats.ai_used = ai_count

    # ── فاز ۷: ارسال ──
    logger.info("📤 فاز ۷: ارسال به کانال‌ها")
    sender = NewsSender()
    sent_items = sender.send_batch(analyzed, max_items=MAX_NEWS_PER_RUN)
    stats.items_sent = len(sent_items)

    # ── فاز ۸: ذخیره نهایی ──
    logger.info("💾 فاز ۸: ذخیره نهایی")
    for item in analyzed:
        storage.update(item)
    storage.save()

    # ذخیره آمار
    duration = time.monotonic() - start_time
    stats.finished_at = datetime.now(timezone.utc).isoformat()
    stats.duration_sec = round(duration, 2)
    stats_mgr.add(stats)
    stats_mgr.save()

    logger.info("=" * 60)
    logger.info("✅ اجرا کامل شد در %.1f ثانیه", duration)
    logger.info(
        "📊 آمار: دریافت=%d | فیلتر=%d | ارسال=%d | AI=%d",
        stats.items_fetched,
        stats.items_filtered,
        stats.items_sent,
        stats.ai_used,
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
