"""
سامانه پایش اخبار محیط‌زیست ایران
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
جریان اصلی:
  1) جمع‌آوری از 11 فید RSS
  2) فیلتر 3 لایه (blacklist → score → category+critical)
  3) حذف تکراری‌ها (link dedup از news.json)
  4) تحلیل AI فقط برای اخبار بحرانی (≤2/اجرا، ≤15/روز)
  5) ارسال به تلگرام + بله
  6) ذخیره در data/news.json
"""

import json
import logging
import os
import time
from datetime import datetime, date
from pathlib import Path

import jdatetime

from src.collector import collect_all_feeds
from src.filter    import filter_news
from src.analyzer  import analyze_batch
from src.sender    import send_to_telegram, send_to_bale
from src.config    import (
    MAX_NEWS_PER_RUN, MAX_STORED_NEWS,
    DELAY_BETWEEN_SENDS, BOT_SIGNATURE,
    AI_ENABLED,
)

# ───────────────────────────────────────────
# لاگ‌گذاری
# ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

DATA_PATH = Path("data/news.json")


# ───────────────────────────────────────────
# ابزارهای کمکی
# ───────────────────────────────────────────
def load_news() -> list[dict]:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_news(news_list: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
    news_list.sort(key=lambda x: x.get("date", ""), reverse=True)
    # حفظ حداکثر MAX_STORED_NEWS خبر
    news_list = news_list[:MAX_STORED_NEWS]
    DATA_PATH.write_text(
        json.dumps(news_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"[save] {len(news_list)} خبر ذخیره شد")


def to_shamsi(dt_str: str) -> str:
    """تبدیل تاریخ میلادی به شمسی"""
    try:
        dt = datetime.fromisoformat(dt_str)
        jd = jdatetime.datetime.fromgregorian(datetime=dt)
        return jd.strftime("%d %B %Y")
    except Exception:
        jd = jdatetime.date.today()
        return jd.strftime("%d %B %Y")


def build_message(item: dict) -> str:
    """ساخت پیام برای تلگرام/بله"""
    category  = item.get("category", "🏛️ محیط زیست")
    title     = item.get("title", "")
    source    = item.get("source", "")
    link      = item.get("link", "")
    date_str  = to_shamsi(item.get("date", ""))
    summary   = item.get("summary", "")[:200].strip()
    ai        = item.get("ai")

    # بخش اصلی پیام
    lines = [
        f"{category}",
        f"",
        f"📰 *{title}*",
        f"",
        f"📝 {summary}",
        f"",
        f"📅 {date_str} | 🗞 {source}",
        f"🔗 {link}",
    ]

    # بخش مشاوره AI (فقط برای اخبار بحرانی تحلیل‌شده)
    if ai:
        sensitivity = ai.get("sensitivity", "")
        emoji       = ai.get("sensitivity_emoji", "🔵")
        urgency     = ai.get("urgency", "")
        action      = ai.get("action", "")
        draft       = ai.get("draft_response", "")

        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🤖 *تحلیل روابط‌عمومی*",
            f"{emoji} حساسیت: {sensitivity} | ⏰ فوریت: {urgency}",
            f"",
            f"💡 *اقدام پیشنهادی:* {action}",
            f"",
            f"📋 *پیش‌نویس پاسخ رسمی:*",
            f"_{draft}_",
        ]

    lines += [f"", f"—", f"{BOT_SIGNATURE}"]
    return "\n".join(lines)


# ───────────────────────────────────────────
# جریان اصلی
# ───────────────────────────────────────────
def main() -> None:
    start_time = time.time()
    logger.info("=" * 50)
    logger.info("🌿 سامانه پایش اخبار محیط‌زیست — شروع اجرا")
    logger.info("=" * 50)

    # مرحله ۱: بارگذاری اخبار قبلی
    existing_news  = load_news()
    existing_links = {n["link"] for n in existing_news if "link" in n}
    logger.info(f"[load] {len(existing_news)} خبر موجود | {len(existing_links)} لینک یکتا")

    # مرحله ۲: جمع‌آوری
    logger.info("[collect] شروع جمع‌آوری از فیدها...")
    raw_items = collect_all_feeds()
    logger.info(f"[collect] {len(raw_items)} آیتم خام دریافت شد")

    # مرحله ۳: فیلتر + حذف تکراری
    new_news = []
    seen_in_run = set()

    for item in raw_items:
        link = item.get("link", "")
        if not link or link in existing_links or link in seen_in_run:
            continue

        feed_url = item.get("feed_url", "")
        filtered = filter_news([item], feed_url)

        if filtered:
            filtered[0]["date"] = filtered[0].get("date") or datetime.now().isoformat()
            new_news.append(filtered[0])
            seen_in_run.add(link)

        if len(new_news) >= MAX_NEWS_PER_RUN:
            break

    logger.info(f"[filter] {len(new_news)} خبر جدید پس از فیلتر")

    if not new_news:
        logger.info("[done] خبر جدیدی یافت نشد.")
        return

    # مرحله ۴: تحلیل AI (فقط بحرانی‌ها)
    critical_count = sum(1 for n in new_news if n.get("critical"))
    logger.info(f"[AI] {critical_count} خبر بحرانی از {len(new_news)} خبر جدید")

    if AI_ENABLED and critical_count > 0:
        new_news = analyze_batch(new_news)
    else:
        logger.info("[AI] غیرفعال یا بدون خبر بحرانی")

    # مرحله ۵: ارسال به کانال‌ها
    sent_count = 0
    for item in new_news:
        message = build_message(item)
        t_ok    = send_to_telegram(message)
        b_ok    = send_to_bale(message)

        if t_ok or b_ok:
            item["sent"] = True
            sent_count  += 1
            logger.info(f"[send ✅] T={t_ok} B={b_ok} | {item['title'][:50]}")
        else:
            item["sent"] = False
            logger.warning(f"[send ❌] {item['title'][:50]}")

        time.sleep(DELAY_BETWEEN_SENDS)

    # مرحله ۶: ذخیره‌سازی
    all_news = new_news + existing_news
    save_news(all_news)

    elapsed = round(time.time() - start_time, 1)
    ai_analyzed = sum(1 for n in new_news if n.get("ai_analyzed"))

    logger.info("=" * 50)
    logger.info(f"✅ اتمام | زمان: {elapsed}s")
    logger.info(f"📊 جمع‌آوری: {len(raw_items)} | فیلتر: {len(new_news)} | ارسال: {sent_count}")
    logger.info(f"🤖 تحلیل AI: {ai_analyzed} خبر بحرانی")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
