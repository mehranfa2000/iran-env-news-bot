# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  main.py  ·  v4.1  ·  هماهنگ‌کننده اصلی سیستم پایش اخبار محیط‌زیست        ║
# ║  ۸ فاز · RawArticle→NewsItem · مدیریت AI · ارسال Telegram+Bale             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone

import jdatetime

from src.agent    import NewsItem, StorageManager, RunStats
from src.analyzer import analyze_news, summarize_news
from src.collector import collect_news, RawArticle
from src.config   import (
    MAX_NEWS_PER_RUN,
    AI_MAX_PER_RUN,
    AI_SUMMARY_MAX_PER_RUN,
    CRITICAL_SCORE_THRESHOLD,
    SCORE_THRESHOLD_DEDICATED,
    SCORE_THRESHOLD_GENERAL,
)
from src.filter   import filter_news
from src.sender   import send_news_item

# ══════════════════════════════════════════════════════════════════════════════
#  لاگ‌گیری
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

# ══════════════════════════════════════════════════════════════════════════════
#  تبدیل RawArticle → NewsItem
# ══════════════════════════════════════════════════════════════════════════════

def _raw_to_newsitem(raw: RawArticle, score: int, category: str, critical: bool) -> NewsItem:
    """
    تبدیل RawArticle (خروجی collector+filter) به NewsItem (ساختار ذخیره‌سازی).
    published_at = زمان دریافت (UTC) — چون فیدهای ایرانی تاریخ استاندارد ندارند.
    """
    now_utc = datetime.now(timezone.utc)

    return NewsItem(
        uid          = raw.uid,
        title        = raw.title,
        link         = raw.link,
        summary      = raw.summary,
        source       = raw.source,
        image_url    = raw.image_url,
        dedicated    = raw.dedicated,
        tags         = raw.tags,
        score        = score,
        category     = category,
        critical     = critical,
        published_at = now_utc.isoformat(),
        shamsi_date  = jdatetime.datetime.fromgregorian(datetime=now_utc).strftime("%Y/%m/%d %H:%M"),
        ai_summary   = None,
        pr_analysis  = None,
        sent         = False,
    )

# ══════════════════════════════════════════════════════════════════════════════
#  هماهنگ‌کننده اصلی
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    run_id   = uuid.uuid4().hex[:8]
    run_stats = RunStats(run_id=run_id)

    logger.info("=" * 60)
    logger.info("🚀 شروع اجرا — run_id: %s", run_id)
    logger.info("=" * 60)

    # ── بارگذاری ذخیره‌سازی ──────────────────────────────────────────────────
    storage = StorageManager()
    storage.load()
    logger.info("📥 %d خبر بارگذاری شد", len(storage.items))

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۱: جمع‌آوری اخبار
    # ════════════════════════════════════════════════════════════════════════
    logger.info("📡 فاز ۱: جمع‌آوری اخبار")
    raw_articles: list[RawArticle] = collect_news()
    run_stats.total_collected = len(raw_articles)

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۲: حذف تکراری (uid-based)
    # ════════════════════════════════════════════════════════════════════════
    logger.info("🔎 فاز ۲: حذف تکراری")
    new_raw = [r for r in raw_articles if not storage.exists(r.uid)]
    logger.info("🆕 %d خبر جدید از %d کل", len(new_raw), len(raw_articles))
    run_stats.new_articles = len(new_raw)

    if not new_raw:
        logger.info("⏭ هیچ خبر جدیدی نیست — پایان اجرا")
        _finalize(storage, run_stats)
        return

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۳: فیلتر محیط‌زیستی (4 لایه)
    # ════════════════════════════════════════════════════════════════════════
    logger.info("🔍 فاز ۳: فیلتر محیط‌زیستی")
    # filter_news انتظار RawArticle دارد و لیستی از
    # (RawArticle, score, category, critical) برمی‌گرداند
    filtered: list[tuple[RawArticle, int, str, bool]] = filter_news(new_raw)
    run_stats.filtered_articles = len(filtered)
    logger.info("✅ %d خبر از فیلتر گذشت", len(filtered))

    if not filtered:
        logger.info("⏭ هیچ خبری فیلتر را رد نکرد — پایان اجرا")
        _finalize(storage, run_stats)
        return

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۴: انتخاب بهترین اخبار (حداکثر MAX_NEWS_PER_RUN)
    # ════════════════════════════════════════════════════════════════════════
    logger.info("📊 فاز ۴: انتخاب بهترین اخبار (حداکثر %d)", MAX_NEWS_PER_RUN)
    # مرتب‌سازی: بحرانی > امتیاز بالا
    filtered.sort(key=lambda t: (t[3], t[1]), reverse=True)
    selected = filtered[:MAX_NEWS_PER_RUN]
    logger.info("📌 %d خبر انتخاب شد", len(selected))

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۵: تبدیل به NewsItem و ذخیره اولیه
    # ════════════════════════════════════════════════════════════════════════
    logger.info("💾 فاز ۵: تبدیل و ذخیره اولیه")
    new_items: list[NewsItem] = []

    for raw, score, category, critical in selected:
        item = _raw_to_newsitem(raw, score, category, critical)
        storage.add(item)
        new_items.append(item)

    storage.save()
    logger.info("✅ %d خبر جدید ذخیره شد", len(new_items))

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۶: تحلیل AI
    # ════════════════════════════════════════════════════════════════════════
    logger.info("🤖 فاز ۶: تحلیل هوش مصنوعی")

    ai_full_count    = 0   # تحلیل کامل ۹ فیلد (بحرانی)
    ai_summary_count = 0   # خلاصه ساده (عادی)
    ai_aborted       = False

    for item in new_items:
        if ai_aborted:
            break

        if item.critical and ai_full_count < AI_MAX_PER_RUN:
            logger.info("🧠 تحلیل کامل: %s", item.title[:50])
            result = analyze_news(item)
            if result is None:
                logger.critical("🚫 مدل AI در دسترس نیست — قطع تحلیل")
                ai_aborted = True
                break
            item.pr_analysis = result
            storage.update(item)
            ai_full_count += 1

        elif not item.critical and ai_summary_count < AI_SUMMARY_MAX_PER_RUN:
            logger.info("📝 خلاصه AI: %s", item.title[:50])
            summary = summarize_news(item)
            if summary is None:
                logger.critical("🚫 مدل AI در دسترس نیست — قطع تحلیل")
                ai_aborted = True
                break
            item.ai_summary = summary
            storage.update(item)
            ai_summary_count += 1

    run_stats.ai_analyzed   = ai_full_count
    run_stats.ai_summarized = ai_summary_count

    # ذخیره پس از AI
    if ai_full_count + ai_summary_count > 0:
        storage.save()
        logger.info(
            "✅ AI — تحلیل کامل: %d | خلاصه: %d",
            ai_full_count, ai_summary_count
        )

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۷: ارسال به کانال‌ها
    # ════════════════════════════════════════════════════════════════════════
    logger.info("📤 فاز ۷: ارسال به تلگرام و بله")
    sent_count   = 0
    failed_count = 0

    # ترتیب ارسال: بحرانی اول
    send_queue = sorted(new_items, key=lambda x: x.critical, reverse=True)

    for item in send_queue:
        success = send_news_item(item)
        if success:
            item.sent = True
            storage.update(item)
            sent_count += 1
            logger.info("✅ ارسال شد: %s", item.title[:50])
        else:
            failed_count += 1
            logger.warning("❌ ارسال ناموفق: %s", item.title[:50])

    run_stats.sent_count   = sent_count
    run_stats.failed_count = failed_count
    logger.info(
        "📊 ارسال — ✅ موفق: %d | ❌ ناموفق: %d",
        sent_count, failed_count
    )

    # ════════════════════════════════════════════════════════════════════════
    #  فاز ۸: ذخیره نهایی و آمار
    # ════════════════════════════════════════════════════════════════════════
    _finalize(storage, run_stats)


# ══════════════════════════════════════════════════════════════════════════════
#  ذخیره نهایی و آمار
# ══════════════════════════════════════════════════════════════════════════════

def _finalize(storage: StorageManager, run_stats: RunStats) -> None:
    """ذخیره نهایی news.json و run_stats.json."""
    logger.info("💾 فاز ۸: ذخیره نهایی")
    storage.save()
    run_stats.finish()
    run_stats.save()
    logger.info("=" * 60)
    logger.info("🏁 پایان اجرا — run_id: %s", run_stats.run_id)
    logger.info(
        "📈 آمار: جمع‌آوری=%d | جدید=%d | فیلتر=%d | AI=%d | ارسال=%d",
        run_stats.total_collected,
        run_stats.new_articles,
        run_stats.filtered_articles,
        run_stats.ai_analyzed,
        run_stats.sent_count,
    )
    logger.info("=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
#  نقطه شروع
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
