"""
تحلیل روزانه ۲۴ ساعته اخبار محیط‌زیست
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- خواندن news.json
- فیلتر اخبار ۲۴ ساعت گذشته
- تحلیل جامع با Gemini 2.0 Flash
- ذخیره در data/daily_analysis.json
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jdatetime
from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import GEMINI_API_KEY, AI_MODEL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_analysis")

DATA_PATH     = Path("data/news.json")
OUTPUT_PATH   = Path("data/daily_analysis.json")


# ═══════════════════════════════════════════
# مدل‌های Pydantic
# ═══════════════════════════════════════════

class NewsItemAnalysis(BaseModel):
    title:       str
    category:    str
    sensitivity: str   # بحرانی / حساس / عادی / مثبت
    sentiment:   str   # منفی / خنثی / مثبت
    summary:     str   # یک جمله
    action:      str   # یک جمله اقدام


class DailyReport(BaseModel):
    overall_risk:       str   # بحرانی / حساس / عادی / مثبت
    executive_summary:  str   # ۳-۴ جمله خلاصه اجرایی
    top_issues:         str   # مهم‌ترین مسائل، کاما جدا
    recommendations:    str   # ۳-۵ توصیه، با | جدا شده
    media_strategy:     str   # ۲ جمله راهبرد رسانه‌ای
    urgent_actions:     str   # اقدامات فوری، با | جدا شده
    positive_points:    str   # نکات مثبت (اگر وجود دارد)
    stakeholders:       str   # سازمان‌های کلیدی، کاما جدا


# ═══════════════════════════════════════════
# ابزارها
# ═══════════════════════════════════════════

def load_last_24h() -> list[dict]:
    """بارگذاری اخبار ۲۴ ساعت گذشته"""
    if not DATA_PATH.exists():
        logger.error("news.json یافت نشد")
        return []

    news = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = []

    for item in news:
        try:
            dt_str = item.get("date", "")
            if not dt_str:
                continue
            # پشتیبانی از فرمت‌های مختلف
            dt_str_clean = dt_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                result.append(item)
        except Exception:
            # اخبار بدون تاریخ معتبر را اضافه کن (احتیاطی)
            result.append(item)

    logger.info(f"[load] {len(result)} خبر در ۲۴ ساعت گذشته")
    return result


def shamsi_now() -> str:
    jd = jdatetime.datetime.now()
    return jd.strftime("%d %B %Y — %H:%M")


def build_summary_text(news_list: list[dict]) -> str:
    """ساخت متن خلاصه برای ارسال به Gemini"""
    lines = []
    for i, item in enumerate(news_list[:30], 1):
        title    = item.get("title", "")
        category = item.get("category", "")
        summary  = item.get("summary", "")[:150]
        critical = "🔴 بحرانی" if item.get("critical") else ""
        lines.append(f"{i}. [{category}] {critical}\nعنوان: {title}\nخلاصه: {summary}\n")
    return "\n".join(lines)


def build_items_text(news_list: list[dict]) -> str:
    """ساخت متن آیتم‌ها برای تحلیل جزئیات"""
    lines = []
    for i, item in enumerate(news_list[:20], 1):
        title   = item.get("title", "")
        summary = item.get("summary", "")[:200]
        cat     = item.get("category", "")
        lines.append(f"خبر {i}: {title} | دسته: {cat} | خلاصه: {summary}")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# تحلیل‌گرها
# ═══════════════════════════════════════════

def analyze_overall(client: genai.Client, news_list: list[dict]) -> DailyReport | None:
    """تحلیل کلی ۲۴ ساعت"""
    summary_text = build_summary_text(news_list)
    critical_count = sum(1 for n in news_list if n.get("critical"))
    categories = {}
    for n in news_list:
        cat = n.get("category", "نامشخص")
        categories[cat] = categories.get(cat, 0) + 1
    cat_text = " | ".join([f"{k}: {v}" for k, v in categories.items()])

    prompt = f"""تو مشاور ارشد روابط عمومی سازمان محیط‌زیست ایران هستی.

آمار ۲۴ ساعت گذشته:
- تعداد کل اخبار: {len(news_list)}
- اخبار بحرانی: {critical_count}
- توزیع دسته‌بندی: {cat_text}

فهرست اخبار:
{summary_text}

یک گزارش مشاوره‌ای جامع و حرفه‌ای برای مدیریت ارشد سازمان بنویس.
پاسخ کاملاً فارسی. کوتاه و کاربردی.

- overall_risk: یکی از [بحرانی، حساس، عادی، مثبت] بر اساس وضعیت کلی
- executive_summary: ۳-۴ جمله خلاصه وضعیت محیط‌زیست امروز
- top_issues: مهم‌ترین ۳-۵ مسئله امروز، با کاما جدا
- recommendations: ۳-۵ توصیه کاربردی، هر توصیه با | جدا شود
- media_strategy: ۲ جمله راهبرد رسانه‌ای پیشنهادی
- urgent_actions: اقدامات فوری ضروری، هر مورد با | جدا شود
- positive_points: نکات مثبت یا دستاوردها (اگر نبود بنویس: موردی یافت نشد)
- stakeholders: سازمان‌های کلیدی درگیر، با کاما جدا"""

    try:
        response = client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DailyReport,
                temperature=0.4,
                max_output_tokens=1024,
            ),
        )
        return response.parsed
    except Exception as e:
        logger.error(f"[overall analysis] خطا: {e}")
        return None


def analyze_items(client: genai.Client, news_list: list[dict]) -> list[dict]:
    """تحلیل جزئی هر خبر (حداکثر ۱۵ خبر)"""
    items_to_analyze = [n for n in news_list if n.get("critical")][:8]
    if not items_to_analyze:
        items_to_analyze = news_list[:5]

    results = []
    for i, item in enumerate(items_to_analyze):
        title   = item.get("title", "")
        summary = item.get("summary", "")[:200]
        cat     = item.get("category", "")

        prompt = f"""تحلیل سریع این خبر محیط‌زیستی برای روابط‌عمومی:
عنوان: {title}
دسته: {cat}
خلاصه: {summary}

پاسخ فارسی کوتاه:
- title: همان عنوان خبر
- category: همان دسته
- sensitivity: یکی از [بحرانی، حساس، عادی، مثبت]
- sentiment: یکی از [منفی، خنثی، مثبت]
- summary: یک جمله تحلیل
- action: یک جمله اقدام پیشنهادی"""

        try:
            response = client.models.generate_content(
                model=AI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=NewsItemAnalysis,
                    temperature=0.3,
                    max_output_tokens=256,
                ),
            )
            parsed = response.parsed
            results.append({
                "title":       parsed.title or title,
                "category":    parsed.category or cat,
                "sensitivity": parsed.sensitivity,
                "sentiment":   parsed.sentiment,
                "summary":     parsed.summary,
                "action":      parsed.action,
                "link":        item.get("link", ""),
                "source":      item.get("source", ""),
            })
            logger.info(f"[item {i+1}] ✅ {title[:50]}")
        except Exception as e:
            logger.warning(f"[item {i+1}] ❌ {e}")

        time.sleep(3)

    return results


# ═══════════════════════════════════════════
# اجرای اصلی
# ═══════════════════════════════════════════

def main():
    logger.info("=" * 50)
    logger.info("🤖 شروع تحلیل روزانه ۲۴ ساعته")
    logger.info("=" * 50)

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY تنظیم نشده!")
        return

    # بارگذاری اخبار
    news_list = load_last_24h()
    if not news_list:
        logger.warning("هیچ خبری در ۲۴ ساعت گذشته یافت نشد")
        output = {
            "generated_at": shamsi_now(),
            "status": "no_news",
            "total_news": 0,
            "critical_count": 0,
            "overall_risk": "عادی",
            "executive_summary": "در ۲۴ ساعت گذشته خبر محیط‌زیستی دریافت نشد.",
            "top_issues": "",
            "recommendations": "",
            "media_strategy": "",
            "urgent_actions": "",
            "positive_points": "",
            "stakeholders": "",
            "news_analyses": [],
            "category_stats": {},
            "source_stats": {},
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    # آمار پایه
    critical_count = sum(1 for n in news_list if n.get("critical"))
    category_stats = {}
    source_stats   = {}
    for n in news_list:
        cat = n.get("category", "نامشخص")
        src = n.get("source", "نامشخص")
        category_stats[cat] = category_stats.get(cat, 0) + 1
        source_stats[src]   = source_stats.get(src, 0) + 1

    logger.info(f"[stats] کل: {len(news_list)} | بحرانی: {critical_count}")

    # تحلیل کلی
    logger.info("[AI] شروع تحلیل کلی...")
    overall = analyze_overall(client, news_list)
    time.sleep(5)

    # تحلیل جزئی
    logger.info("[AI] شروع تحلیل جزئی اخبار...")
    item_analyses = analyze_items(client, news_list)

    # ساخت خروجی
    output = {
        "generated_at":     shamsi_now(),
        "status":           "success",
        "total_news":       len(news_list),
        "critical_count":   critical_count,
        "category_stats":   category_stats,
        "source_stats":     source_stats,
        "overall_risk":     overall.overall_risk    if overall else "حساس",
        "executive_summary":overall.executive_summary if overall else "تحلیل در دسترس نیست.",
        "top_issues":       overall.top_issues      if overall else "",
        "recommendations":  overall.recommendations if overall else "",
        "media_strategy":   overall.media_strategy  if overall else "",
        "urgent_actions":   overall.urgent_actions  if overall else "",
        "positive_points":  overall.positive_points if overall else "",
        "stakeholders":     overall.stakeholders    if overall else "",
        "news_analyses":    item_analyses,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    logger.info("=" * 50)
    logger.info(f"✅ تحلیل روزانه ذخیره شد → {OUTPUT_PATH}")
    logger.info(f"📊 کل: {len(news_list)} | بحرانی: {critical_count} | آیتم‌های تحلیل‌شده: {len(item_analyses)}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
