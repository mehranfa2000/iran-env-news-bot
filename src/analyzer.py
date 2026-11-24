# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/analyzer.py  ·  v4.1  ·  تحلیل هوش مصنوعی با Gemini                  ║
# ║  تحلیل کامل ۹ فیلد (بحرانی) · خلاصه ساده (عادی) · fast-fail on 404       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Optional

import google.generativeai as genai

from src.agent  import NewsItem
from src.config import (
    AI_MODEL,
    AI_TEMPERATURE,
    AI_TIMEOUT,
    GEMINI_API_KEY,
)

logger = logging.getLogger(__name__)

# ── راه‌اندازی Gemini ─────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. ساختار تحلیل PR — ۹ فیلد
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PRAnalysis:
    """
    تحلیل کامل روابط‌عمومی برای اخبار بحرانی.
    ۹ فیلد تخصصی برای مدیریت بحران.
    """
    sensitivity:    str   # سطح حساسیت: بالا / متوسط / پایین
    sentiment:      str   # احساس کلی: منفی / خنثی / مثبت
    summary:        str   # خلاصه تحلیلی (۲-۳ جمله)
    risk_factors:   str   # عوامل خطر و تهدیدهای احتمالی
    action:         str   # اقدام پیشنهادی فوری
    draft_response: str   # پیش‌نویس پاسخ رسمی سازمان
    stakeholders:   str   # ذی‌نفعان اصلی (سازمان‌ها، رسانه‌ها، عموم)
    urgency:        str   # فوریت: فوری / ۲۴ ساعت / هفتگی
    media_risk:     str   # خطر رسانه‌ای: بالا / متوسط / پایین

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PRAnalysis":
        return cls(
            sensitivity    = data.get("sensitivity",    "نامشخص"),
            sentiment      = data.get("sentiment",      "خنثی"),
            summary        = data.get("summary",        ""),
            risk_factors   = data.get("risk_factors",   ""),
            action         = data.get("action",         ""),
            draft_response = data.get("draft_response", ""),
            stakeholders   = data.get("stakeholders",   ""),
            urgency        = data.get("urgency",        "۲۴ ساعت"),
            media_risk     = data.get("media_risk",     "متوسط"),
        )

# ══════════════════════════════════════════════════════════════════════════════
#  ۲. متغیر نگهدارنده مدل — یک بار ساخته می‌شود
# ══════════════════════════════════════════════════════════════════════════════

_model: Optional[genai.GenerativeModel] = None
_model_dead: bool = False   # اگر True → مدل در دسترس نیست → هیچ درخواستی نزن


def _get_model() -> Optional[genai.GenerativeModel]:
    """
    مدل Gemini را برمی‌گرداند.
    اگر مدل قبلاً 404 داده → بلافاصله None برمی‌گرداند.
    """
    global _model, _model_dead

    if _model_dead:
        return None

    if _model is None:
        _model = genai.GenerativeModel(
            model_name=AI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=AI_TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        logger.info("🤖 مدل Gemini بارگذاری شد: %s", AI_MODEL)

    return _model


def _mark_model_dead() -> None:
    """مدل را مرده علامت می‌زند — هیچ درخواست بعدی ارسال نمی‌شود."""
    global _model_dead
    _model_dead = True
    logger.critical(
        "🚫 مدل '%s' در دسترس نیست — تمام درخواست‌های AI متوقف شد",
        AI_MODEL
    )

# ══════════════════════════════════════════════════════════════════════════════
#  ۳. تابع مرکزی ارسال به Gemini
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(prompt: str) -> Optional[str]:
    """
    ارسال یک prompt به Gemini و دریافت پاسخ JSON.

    fast-fail: اگر خطای 404 «no longer available» دریافت شد →
    بلافاصله None برمی‌گرداند بدون retry.
    برای سایر خطاها → یک بار retry با تاخیر ۵ ثانیه.
    """
    model = _get_model()
    if model is None:
        return None

    for attempt in range(1, 3):   # حداکثر ۲ بار تلاش
        try:
            response = model.generate_content(
                prompt,
                request_options={"timeout": AI_TIMEOUT},
            )
            return response.text

        except Exception as exc:
            err_str = str(exc).lower()

            # ── fast-fail: مدل حذف شده ──────────────────────────────────────
            # gemini-2.0-flash از ژوئن ۲۰۲۶ حذف شده و HTTP 404 می‌دهد
            if "404" in err_str and (
                "no longer available" in err_str
                or "not found" in err_str
                or "deprecated" in err_str
                or "model" in err_str
            ):
                _mark_model_dead()
                return None   # بدون retry

            # ── rate limit → صبر کن ─────────────────────────────────────────
            if "429" in err_str or "quota" in err_str or "rate" in err_str:
                wait = 10 * attempt
                logger.warning(
                    "⏳ rate limit — %d ثانیه صبر (تلاش %d/2)",
                    wait, attempt
                )
                time.sleep(wait)
                continue

            # ── سایر خطاها ──────────────────────────────────────────────────
            logger.error("❌ خطای Gemini (تلاش %d/2): %s", attempt, exc)
            if attempt == 1:
                time.sleep(5)

    return None

# ══════════════════════════════════════════════════════════════════════════════
#  ۴. تحلیل کامل ۹ فیلد — برای اخبار بحرانی
# ══════════════════════════════════════════════════════════════════════════════

_ANALYZE_PROMPT = """
تو یک متخصص روابط‌عمومی و مدیریت بحران سازمان حفاظت محیط‌زیست ایران هستی.

خبر زیر را تحلیل کن و خروجی را دقیقاً به فرمت JSON زیر بده:

{{
  "sensitivity": "سطح حساسیت: بالا یا متوسط یا پایین",
  "sentiment": "احساس کلی خبر: منفی یا خنثی یا مثبت",
  "summary": "خلاصه تحلیلی ۲ تا ۳ جمله به فارسی",
  "risk_factors": "عوامل خطر و تهدیدهای احتمالی برای سازمان",
  "action": "اقدام فوری پیشنهادی برای سازمان",
  "draft_response": "پیش‌نویس پاسخ رسمی سازمان به این خبر (۲-۳ جمله رسمی)",
  "stakeholders": "ذی‌نفعان اصلی: سازمان‌ها، رسانه‌ها، گروه‌های مردمی",
  "urgency": "فوریت اقدام: فوری یا ۲۴ ساعت یا هفتگی",
  "media_risk": "خطر رسانه‌ای: بالا یا متوسط یا پایین"
}}

عنوان خبر: {title}
منبع: {source}
خلاصه: {summary}

فقط JSON خالص برگردان. بدون توضیح اضافه.
"""


def analyze_news(item: NewsItem) -> Optional[dict]:
    """
    تحلیل کامل ۹ فیلد برای اخبار بحرانی.

    Returns:
        dict (PRAnalysis.to_dict()) در صورت موفقیت
        None در صورت خطا یا در دسترس نبودن مدل
    """
    logger.info("🧠 تحلیل کامل AI: %s", item.title[:60])

    prompt = _ANALYZE_PROMPT.format(
        title   = item.title,
        source  = item.source,
        summary = item.summary[:400],
    )

    raw_response = _call_gemini(prompt)
    if raw_response is None:
        return None

    try:
        # پاک‌سازی پاسخ (گاهی Gemini markdown اضافه می‌کند)
        clean = raw_response.strip()
        clean = clean.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        data = json.loads(clean)
        analysis = PRAnalysis.from_dict(data)
        logger.info("✅ تحلیل AI موفق: %s", item.title[:40])
        return analysis.to_dict()

    except json.JSONDecodeError as exc:
        logger.error("❌ خطای JSON در پاسخ Gemini: %s | پاسخ: %s", exc, raw_response[:200])
        return None
    except Exception as exc:
        logger.error("❌ خطا در پردازش پاسخ Gemini: %s", exc)
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  ۵. خلاصه ساده — برای اخبار عادی
# ══════════════════════════════════════════════════════════════════════════════

_SUMMARY_PROMPT = """
یک خلاصه کوتاه و حرفه‌ای از خبر زیر بنویس.
خلاصه باید:
- دقیقاً ۲ جمله باشد
- به فارسی روان و رسمی
- نکات کلیدی محیط‌زیستی را برجسته کند
- بدون هیچ توضیح یا مقدمه اضافه

فقط متن خلاصه را برگردان (بدون JSON، بدون گیومه):

عنوان: {title}
خلاصه اولیه: {summary}
"""


def summarize_news(item: NewsItem) -> Optional[str]:
    """
    خلاصه ساده ۲ جمله‌ای برای اخبار عادی.

    Returns:
        str در صورت موفقیت
        None در صورت خطا یا در دسترس نبودن مدل
    """
    logger.info("📝 خلاصه AI: %s", item.title[:60])

    prompt = _SUMMARY_PROMPT.format(
        title   = item.title,
        summary = item.summary[:400],
    )

    raw_response = _call_gemini(prompt)
    if raw_response is None:
        return None

    result = raw_response.strip().strip('"').strip("'").strip()

    if len(result) < 10:
        logger.warning("⚠️ خلاصه AI خیلی کوتاه: %s", result)
        return None

    logger.info("✅ خلاصه AI موفق: %s", item.title[:40])
    return result[:600]   # حداکثر ۶۰۰ کاراکتر


# ══════════════════════════════════════════════════════════════════════════════
#  ۶. بررسی وضعیت مدل
# ══════════════════════════════════════════════════════════════════════════════

def is_ai_available() -> bool:
    """بررسی می‌کند آیا مدل AI در دسترس است."""
    return not _model_dead
