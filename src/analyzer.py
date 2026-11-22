"""
تحلیلگر هوش مصنوعی — Gemini 2.0 Flash
فقط اخبار بحرانی (critical=True) را تحلیل می‌کند
حداکثر AI_MAX_PER_RUN خبر در هر اجرا
حداکثر AI_MAX_PER_DAY خبر در کل روز
خروجی: مشاوره روابط‌عمومی کوتاه و کاربردی
"""

import json
import logging
import time
from datetime import date

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import (
    GEMINI_API_KEY, AI_ENABLED, AI_MODEL,
    AI_MAX_PER_RUN, AI_MAX_PER_DAY,
    AI_TIMEOUT, AI_RETRY_ATTEMPTS,
)

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────
# مدل خروجی ساختاریافته (Pydantic)
# ───────────────────────────────────────────
class CriticalAnalysis(BaseModel):
    sensitivity:       str   # بحرانی / حساس / عادی / مثبت
    sentiment:         str   # منفی / خنثی / مثبت
    one_line_summary:  str   # یک جمله تحلیل
    action:            str   # یک جمله اقدام پیشنهادی
    draft_response:    str   # دو جمله پیش‌نویس رسمی
    stakeholders:      str   # سازمان‌های ذینفع (کاما جدا)
    urgency:           str   # فوری / ۲۴ ساعت / هفتگی / نیازی نیست


# ───────────────────────────────────────────
# نگاشت حساسیت به ایموجی و برچسب
# ───────────────────────────────────────────
SENSITIVITY_MAP = {
    "بحرانی": "🔴",
    "حساس":   "🟡",
    "عادی":   "🔵",
    "مثبت":   "🟢",
}


def _build_prompt(title: str, summary: str) -> str:
    return f"""تو مشاور ارشد روابط عمومی سازمان محیط‌زیست ایران هستی.
این خبر بحرانی را سریع تحلیل کن و پاسخ کوتاه و کاربردی بده:

عنوان خبر: {title}
خلاصه خبر: {summary[:300]}

پاسخ کاملاً فارسی. هر بخش بسیار کوتاه (حداکثر ۲ جمله):
- sensitivity: یکی از [بحرانی، حساس، عادی، مثبت]
- sentiment: یکی از [منفی، خنثی، مثبت]
- one_line_summary: یک جمله تحلیل اصلی
- action: یک جمله اقدام پیشنهادی فوری
- draft_response: دو جمله پیش‌نویس پاسخ رسمی سازمان
- stakeholders: سازمان‌های ذینفع با کاما
- urgency: یکی از [فوری، ۲۴ ساعت، هفتگی، نیازی نیست]"""


def _count_today_analyzed(news_list: list[dict]) -> int:
    """تعداد اخباری که امروز تحلیل AI شده‌اند"""
    today = date.today().isoformat()
    return sum(
        1 for n in news_list
        if n.get("ai_analyzed") and n.get("date", "").startswith(today)
    )


def _analyze_one(client: genai.Client, title: str, summary: str) -> dict | None:
    """تحلیل یک خبر با Gemini"""
    prompt = _build_prompt(title, summary)

    for attempt in range(1, AI_RETRY_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=AI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CriticalAnalysis,
                    temperature=0.3,
                    max_output_tokens=512,
                ),
            )
            parsed: CriticalAnalysis = response.parsed
            emoji = SENSITIVITY_MAP.get(parsed.sensitivity, "🔵")

            return {
                "sensitivity":      parsed.sensitivity,
                "sensitivity_emoji": emoji,
                "sentiment":        parsed.sentiment,
                "summary":          parsed.one_line_summary,
                "action":           parsed.action,
                "draft_response":   parsed.draft_response,
                "stakeholders":     parsed.stakeholders,
                "urgency":          parsed.urgency,
            }

        except Exception as e:
            logger.warning(f"[AI attempt {attempt}/{AI_RETRY_ATTEMPTS}] {e}")
            if attempt < AI_RETRY_ATTEMPTS:
                time.sleep(5)

    return None


def _fallback_analysis(title: str) -> dict:
    """تحلیل پشتیبان در صورت خطای AI"""
    return {
        "sensitivity":       "حساس",
        "sensitivity_emoji": "🟡",
        "sentiment":         "منفی",
        "summary":           "نیاز به بررسی دستی توسط کارشناس.",
        "action":            "پیگیری و بررسی توسط واحد روابط عمومی.",
        "draft_response":    "سازمان محیط‌زیست موضوع را با جدیت پیگیری می‌کند.",
        "stakeholders":      "سازمان محیط‌زیست",
        "urgency":           "۲۴ ساعت",
    }


def analyze_batch(news_list: list[dict]) -> list[dict]:
    """
    تحلیل دسته‌ای اخبار بحرانی.
    - فقط آیتم‌هایی که critical=True دارند
    - رعایت AI_MAX_PER_RUN و AI_MAX_PER_DAY
    - 2 ثانیه delay بین درخواست‌ها (rate limit)
    """
    if not AI_ENABLED:
        logger.info("[AI] غیرفعال — GEMINI_API_KEY تنظیم نشده")
        return news_list

    # بررسی سقف روزانه
    daily_used = _count_today_analyzed(news_list)
    daily_remaining = AI_MAX_PER_DAY - daily_used

    if daily_remaining <= 0:
        logger.info(f"[AI] سقف روزانه ({AI_MAX_PER_DAY}) تکمیل شده")
        return news_list

    client     = genai.Client(api_key=GEMINI_API_KEY)
    run_count  = 0
    candidates = [n for n in news_list if n.get("critical") and not n.get("ai_analyzed")]

    logger.info(
        f"[AI] {len(candidates)} خبر بحرانی یافت شد | "
        f"سقف اجرا: {AI_MAX_PER_RUN} | "
        f"باقیمانده روزانه: {daily_remaining}"
    )

    for item in candidates:
        if run_count >= AI_MAX_PER_RUN:
            logger.info(f"[AI] سقف اجرا ({AI_MAX_PER_RUN}) تکمیل شد")
            break
        if run_count >= daily_remaining:
            logger.info(f"[AI] سقف روزانه باقیمانده تکمیل شد")
            break

        title   = item.get("title", "")
        summary = item.get("summary", "") or item.get("content", "")

        logger.info(f"[AI] تحلیل: {title[:60]}")
        result = _analyze_one(client, title, summary)

        if result:
            item["ai"] = result
            logger.info(
                f"[AI ✅] حساسیت={result['sensitivity']} "
                f"فوریت={result['urgency']}"
            )
        else:
            item["ai"] = _fallback_analysis(title)
            logger.warning(f"[AI ⚠️] fallback برای: {title[:50]}")

        item["ai_analyzed"] = True
        run_count += 1

        # 2 ثانیه delay (rate limit رایگان = 10 درخواست/دقیقه)
        if run_count < min(AI_MAX_PER_RUN, daily_remaining):
            time.sleep(2)

    logger.info(f"[AI] تکمیل — {run_count} خبر تحلیل شد")
    return news_list
