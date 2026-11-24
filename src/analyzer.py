# src/analyzer.py
"""
تحلیل هوشمند اخبار با Gemini 2.0-flash
تحلیل کامل ۹ فیلدی برای خبرهای بحرانی
خلاصه‌سازی برای خبرهای عادی
نسخه ۴.۰
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import google.generativeai as genai

from agent import NewsItem, PRAnalysis
from config import (
    GEMINI_API_KEY,
    AI_MODEL,
    AI_TIMEOUT,
)

logger = logging.getLogger("analyzer")

# ── راه‌اندازی Gemini ──
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    _model = genai.GenerativeModel(AI_MODEL)
else:
    _model = None
    logger.warning("⚠️ GEMINI_API_KEY تنظیم نشده")

# پرچم قطع سریع
_model_dead: bool = False


# ══════════════════════════════════════════════════════════════════
# تابع فراخوانی Gemini
# ══════════════════════════════════════════════════════════════════

def _call_gemini(prompt: str) -> Optional[str]:
    """فراخوانی API با مدیریت خطا — قطع فوری روی 404"""
    global _model_dead

    if _model_dead:
        logger.warning("🚫 مدل مرده است — از تحلیل صرف‌نظر شد")
        return None

    if _model is None:
        return None

    for attempt in range(1, 4):
        try:
            response = _model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                    max_output_tokens=2048,
                ),
                request_options={"timeout": AI_TIMEOUT},
            )
            return response.text

        except Exception as e:
            err_str = str(e)

            # ── قطع فوری روی 404 (مدل منسوخ) ──
            if "404" in err_str and (
                "no longer available" in err_str
                or "not found" in err_str.lower()
                or "deprecated" in err_str.lower()
            ):
                logger.critical(
                    "🚫 مدل '%s' در دسترس نیست (404) — تمام تحلیل‌های این اجرا لغو شد",
                    AI_MODEL,
                )
                _model_dead = True
                return None

            # ── 429: محدودیت نرخ — ۶۰ ثانیه صبر ──
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                logger.warning("⏳ محدودیت نرخ Gemini — ۶۰ ثانیه صبر")
                time.sleep(60)
                continue

            # ── سایر خطاها — backoff نمایی ──
            wait = 2 ** attempt
            logger.warning("⚠️ خطای Gemini (تلاش %d): %s — %ds صبر", attempt, err_str[:80], wait)
            time.sleep(wait)

    return None


# ══════════════════════════════════════════════════════════════════
# خلاصه‌سازی (خبرهای عادی)
# ══════════════════════════════════════════════════════════════════

def summarize_news(item: NewsItem) -> Optional[str]:
    """تولید خلاصه ۱۵۰ کلمه‌ای برای خبر عادی"""
    prompt = f"""
شما دستیار روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستید.
یک خلاصه کوتاه و حرفه‌ای (حداکثر ۱۵۰ کلمه) به فارسی برای این خبر بنویسید.

عنوان: {item.title}
متن: {item.summary[:800]}
منبع: {item.source}

پاسخ را به صورت JSON با کلید "summary" برگردانید:
{{"summary": "خلاصه خبر اینجا"}}
"""
    raw = _call_gemini(prompt)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data.get("summary", "").strip() or None
    except json.JSONDecodeError:
        # استخراج متن ساده
        clean = raw.strip().strip('"').strip()
        return clean[:300] if clean else None


# ══════════════════════════════════════════════════════════════════
# تحلیل کامل ۹ فیلدی (خبرهای بحرانی)
# ══════════════════════════════════════════════════════════════════

def analyze_critical_news(item: NewsItem) -> Optional[PRAnalysis]:
    """تحلیل کامل ۹ فیلده روابط‌عمومی برای خبر بحرانی"""
    prompt = f"""
شما تحلیل‌گر ارشد روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستید.
این خبر بحرانی را تحلیل کامل کنید و پاسخ را دقیقاً به صورت JSON برگردانید.

عنوان: {item.title}
متن: {item.summary[:1000]}
منبع: {item.source}
تاریخ: {item.shamsi_date}

پاسخ JSON (فارسی، دقیق، حرفه‌ای):
{{
  "sensitivity": "یکی از: کم | متوسط | بالا | بحرانی",
  "sentiment": "یکی از: مثبت | منفی | خنثی | مختلط",
  "summary": "خلاصه تحلیلی ۱۵۰ کلمه",
  "risk_factors": "عوامل ریسک و خطرات احتمالی",
  "action": "اقدام فوری پیشنهادی سازمان",
  "draft_response": "پیش‌نویس پاسخ رسانه‌ای حرفه‌ای",
  "stakeholders": "ذی‌نفعان اصلی این خبر",
  "urgency": "یکی از: فوری | ۲۴ ساعت | هفتگی",
  "media_risk": "یکی از: کم | متوسط | بالا"
}}
"""
    raw = _call_gemini(prompt)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return PRAnalysis(
            sensitivity=data.get("sensitivity", "متوسط"),
            sentiment=data.get("sentiment", "خنثی"),
            summary=data.get("summary", "")[:500],
            risk_factors=data.get("risk_factors", "")[:300],
            action=data.get("action", "")[:300],
            draft_response=data.get("draft_response", "")[:500],
            stakeholders=data.get("stakeholders", "")[:200],
            urgency=data.get("urgency", "۲۴ ساعت"),
            media_risk=data.get("media_risk", "متوسط"),
        )
    except json.JSONDecodeError as e:
        logger.warning("⚠️ خطای JSON در تحلیل بحرانی: %s | raw: %s", e, raw[:100])
        return None


# ══════════════════════════════════════════════════════════════════
# کلاس اصلی تحلیل‌گر
# ══════════════════════════════════════════════════════════════════

class NewsAnalyzer:
    """مدیریت تحلیل هوشمند اخبار"""

    def __init__(
        self,
        max_critical: int = 5,
        max_summary: int = 5,
    ) -> None:
        self.max_critical = max_critical
        self.max_summary = max_summary
        self._critical_count = 0
        self._summary_count = 0

    def analyze(self, item: NewsItem) -> NewsItem:
        """تحلیل یک خبر"""
        global _model_dead

        if _model_dead or _model is None:
            return item

        if item.is_critical and self._critical_count < self.max_critical:
            logger.info("🧠 تحلیل بحرانی: %s", item.title[:50])
            pr = analyze_critical_news(item)
            if pr:
                item.pr_analysis = pr
                item.ai_summary = pr.summary
                self._critical_count += 1

        elif not item.is_critical and self._summary_count < self.max_summary:
            logger.info("📝 خلاصه‌سازی: %s", item.title[:50])
            summary = summarize_news(item)
            if summary:
                item.ai_summary = summary
                self._summary_count += 1

        return item

    def analyze_batch(self, items: list[NewsItem]) -> list[NewsItem]:
        """تحلیل دسته‌ای اخبار"""
        result = []
        for item in items:
            result.append(self.analyze(item))
            if _model_dead:
                logger.warning("🛑 مدل مرده — تحلیل دسته‌ای متوقف شد")
                # بقیه بدون تحلیل اضافه می‌شوند
                result.extend(items[len(result):])
                break
        logger.info(
            "🤖 تحلیل کامل شد: %d بحرانی، %d خلاصه",
            self._critical_count, self._summary_count,
        )
        return result
