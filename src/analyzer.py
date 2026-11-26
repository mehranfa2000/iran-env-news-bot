"""
analyzer.py — تحلیل AI با Google Gemini
نسخه: 4.2.0

تغییرات v4.2:
- سقف روزانه (AI_MAX_PER_DAY) در run_stats.json persist می‌شود
  → بین ران‌های مختلف حفظ می‌شود (قبلاً هر ران از ۰ شروع می‌کرد)
- Validation کامل خروجی JSON از Gemini
- Fast-fail فقط برای HTTP 404 مدل deprecated
- Rate limit: sleep بین درخواست‌ها (10 RPM free tier)
- تابع load_ai_usage() برای خواندن از main.py
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ─── تنظیمات (با override از env) ────────────────────────────────────────────
AI_MODEL           = os.environ.get("AI_MODEL",    "gemini-3.6-flash")
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
AI_MAX_PER_RUN     = int(os.environ.get("AI_MAX_PER_RUN",     "5"))
AI_SUMMARY_MAX     = int(os.environ.get("AI_SUMMARY_MAX",     "5"))
AI_MAX_PER_DAY     = int(os.environ.get("AI_MAX_PER_DAY",     "20"))
AI_TIMEOUT_SEC     = int(os.environ.get("AI_TIMEOUT_SEC",     "30"))
AI_RPM_SLEEP       = 6.5     # ثانیه بین درخواست‌ها (10 RPM → حداقل ۶s)

STATS_PATH = Path(os.environ.get("STATS_JSON_PATH", "data/run_stats.json"))

# ─── فیلدهای اجباری PR Analysis ──────────────────────────────────────────────
_PR_REQUIRED = frozenset({
    "sensitivity", "sentiment", "summary",
    "risk_factors", "action", "draft_response",
    "stakeholders", "urgency", "media_risk",
})

_PR_DEFAULTS: dict[str, Any] = {
    "sensitivity":    "نامشخص",
    "sentiment":      "خنثی",
    "summary":        "",
    "risk_factors":   [],
    "action":         "بررسی بیشتر",
    "draft_response": "",
    "stakeholders":   [],
    "urgency":        "عادی",
    "media_risk":     "نامشخص",
}


# ══════════════════════════════════════════════════════════════════════════════
# وضعیت مدل — Singleton در سطح ماژول
# ══════════════════════════════════════════════════════════════════════════════
_model_dead = False


def _mark_model_dead(reason: str = "") -> None:
    global _model_dead
    _model_dead = True
    log.critical(f"🚫 مدل AI مرده — ادامه ران بدون AI. دلیل: {reason}")


def is_model_dead() -> bool:
    return _model_dead


def _is_fatal_error(err: str) -> bool:
    """
    تعیین می‌کند آیا خطا از نوع fatal است (مدل deprecated/deleted).
    فقط HTTP 404 با پیام‌های مشخص fatal است.
    429, 500, timeout → retry می‌شوند.
    """
    return "404" in err and any(
        kw in err for kw in ("not found", "no longer", "deprecated", "deleted")
    )


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت سقف روزانه (Persistent بین ران‌ها)
# ══════════════════════════════════════════════════════════════════════════════
def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_ai_usage() -> int:
    """
    تعداد فراخوانی‌های AI امروز را از run_stats.json می‌خواند.
    Public API — از main.py هم فراخوانی می‌شود.
    """
    try:
        if STATS_PATH.exists() and STATS_PATH.stat().st_size > 0:
            data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
            if data.get("ai_date") == _today_str():
                val = data.get("ai_used_today", 0)
                return int(val) if isinstance(val, (int, float)) else 0
    except Exception as e:
        log.debug(f"خطا در خواندن ai_used_today: {e}")
    return 0


def _save_ai_usage(count: int) -> None:
    """
    تعداد فراخوانی‌های AI امروز را در run_stats.json ذخیره می‌کند.
    فقط دو فیلد ai_date و ai_used_today را بروز می‌کند
    تا بقیه فیلدها دست‌نخورده بمانند.
    """
    try:
        existing: dict = {}
        if STATS_PATH.exists() and STATS_PATH.stat().st_size > 0:
            try:
                existing = json.loads(STATS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        existing["ai_date"]       = _today_str()
        existing["ai_used_today"] = count

        STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATS_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.debug(f"ai_used_today={count} ذخیره شد")
    except Exception as e:
        log.warning(f"ذخیره ai_used_today ناموفق: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ساخت مدل Gemini
# ══════════════════════════════════════════════════════════════════════════════
def _build_model():
    """
    مدل Gemini را می‌سازد.
    Returns None اگر API key نداشت یا ساخت ناموفق بود.
    """
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY تنظیم نشده — AI غیرفعال")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(AI_MODEL)
        log.info(f"✅ مدل AI: {AI_MODEL}")
        return model
    except Exception as e:
        log.error(f"خطا در ساخت مدل AI: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Validation خروجی AI
# ══════════════════════════════════════════════════════════════════════════════
def _validate_pr(data: Any) -> Optional[dict]:
    """
    خروجی JSON مدل را validate می‌کند.
    - اگر dict نبود → None
    - فیلدهای خالی را با default پر می‌کند (رد نمی‌کند)
    """
    if not isinstance(data, dict):
        log.warning(f"خروجی AI dict نیست: {type(data)}")
        return None

    # پر کردن فیلدهای خالی با default
    missing = _PR_REQUIRED - set(data.keys())
    if missing:
        log.debug(f"فیلدهای PR پر شد با default: {missing}")
        for f in missing:
            data[f] = _PR_DEFAULTS[f]

    # اعتبارسنجی مقادیر enum
    valid_sensitivity = {"بالا", "متوسط", "پایین", "نامشخص"}
    valid_urgency     = {"فوری", "عادی", "قابل تعویق", "نامشخص"}
    valid_sentiment   = {"منفی", "خنثی", "مثبت", "نامشخص"}

    if data.get("sensitivity") not in valid_sensitivity:
        data["sensitivity"] = "نامشخص"
    if data.get("urgency") not in valid_urgency:
        data["urgency"] = "عادی"
    if data.get("sentiment") not in valid_sentiment:
        data["sentiment"] = "خنثی"

    # اطمینان از list بودن فیلدهای list
    for list_field in ("risk_factors", "stakeholders"):
        if not isinstance(data.get(list_field), list):
            data[list_field] = []

    return data


# ══════════════════════════════════════════════════════════════════════════════
# تحلیل بحرانی (۹ فیلد PR)
# ══════════════════════════════════════════════════════════════════════════════
def _analyze_critical(model, item) -> Optional[dict]:
    """
    تحلیل کامل ۹ فیلدی برای خبر بحرانی.
    Returns None اگر ناموفق بود.
    """
    prompt = f"""تو یک متخصص ارشد روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستی.
این خبر **بحرانی** محیط‌زیستی را تحلیل کن.

━━━ اطلاعات خبر ━━━
عنوان: {item.title}
خلاصه: {(item.summary or '')[:600]}
منبع: {item.source}
━━━━━━━━━━━━━━━━━━━

دقیقاً یک JSON با این ساختار برگردان (فقط JSON، بدون توضیح):
{{
  "sensitivity":    "بالا یا متوسط یا پایین",
  "sentiment":      "منفی یا خنثی یا مثبت",
  "summary":        "خلاصه دو جمله‌ای حرفه‌ای فارسی",
  "risk_factors":   ["ریسک اول", "ریسک دوم"],
  "action":         "اقدام فوری پیشنهادی (یک جمله)",
  "draft_response": "پیش‌نویس پاسخ رسمی (۲-۳ جمله رسمی فارسی)",
  "stakeholders":   ["ذینفع اول", "ذینفع دوم"],
  "urgency":        "فوری یا عادی یا قابل تعویق",
  "media_risk":     "بالا یا متوسط یا پایین"
}}"""

    try:
        import google.generativeai as genai

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.3,
                max_output_tokens=800,
            ),
            request_options={"timeout": AI_TIMEOUT_SEC},
        )
        raw_text = response.text.strip()

        # تلاش برای parse JSON
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # گاهی مدل backtick اضافه می‌کند
            cleaned = raw_text.strip("`").strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            data = json.loads(cleaned)

        return _validate_pr(data)

    except json.JSONDecodeError as e:
        log.warning(f"JSON parse ناموفق برای تحلیل بحرانی: {e}")
        return None
    except Exception as e:
        err = str(e).lower()
        if _is_fatal_error(err):
            _mark_model_dead(reason=str(e)[:100])
        else:
            log.error(f"خطا در تحلیل بحرانی '{item.title[:40]}': {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# خلاصه‌سازی (خبر معمولی)
# ══════════════════════════════════════════════════════════════════════════════
def _summarize(model, item) -> Optional[str]:
    """
    خلاصه کوتاه و حرفه‌ای برای خبر معمولی.
    Returns None اگر ناموفق بود.
    """
    prompt = f"""یک جمله خلاصه فارسی حرفه‌ای از این خبر محیط‌زیستی بنویس.
حداکثر ۲۵ کلمه. فقط متن خلاصه، بدون هیچ توضیح یا مقدمه.

عنوان: {item.title}
متن: {(item.summary or '')[:400]}"""

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature":    0.2,
                "max_output_tokens": 80,
            },
            request_options={"timeout": AI_TIMEOUT_SEC},
        )
        text = response.text.strip()
        # محدودیت طول خروجی
        return text[:200] if text else None

    except Exception as e:
        err = str(e).lower()
        if _is_fatal_error(err):
            _mark_model_dead(reason=str(e)[:100])
        else:
            log.warning(f"خطا در خلاصه '{item.title[:40]}': {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# تابع اصلی
# ══════════════════════════════════════════════════════════════════════════════
def analyze_items(
    items:        list,
    max_critical: int = AI_MAX_PER_RUN,
    max_summary:  int = AI_SUMMARY_MAX,
) -> tuple[list, int, int]:
    """
    تحلیل AI آیتم‌ها با مدیریت سقف روزانه پایدار.

    الگوریتم:
    1. بارگذاری ai_used_today از فایل (نه متغیر موقت)
    2. اولویت: خبرهای بحرانی → بعد خلاصه معمولی
    3. بعد از هر فراخوانی موفق → ذخیره فوری در فایل
    4. اگر مدل 404 داد → fast-fail کل ران

    Returns:
        (items_updated, critical_count, summary_count)
    """
    # ── بررسی پیش‌نیاز ────────────────────────────────────────────────────────
    if _model_dead:
        log.warning("مدل AI مرده — تحلیل رد شد")
        return items, 0, 0

    # بارگذاری سقف روزانه از فایل (پایدار بین ران‌ها)
    ai_used = load_ai_usage()
    log.info(f"📊 AI امروز: {ai_used}/{AI_MAX_PER_DAY} استفاده شده")

    if ai_used >= AI_MAX_PER_DAY:
        log.warning(f"⚠️  سقف روزانه AI ({AI_MAX_PER_DAY}) کامل — رد شد")
        return items, 0, 0

    model = _build_model()
    if model is None:
        return items, 0, 0

    critical_done = 0
    summary_done  = 0

    for item in items:
        # ── بررسی توقف ────────────────────────────────────────────────────────
        if _model_dead:
            log.warning("مدل مرد — ادامه متوقف")
            break
        if ai_used >= AI_MAX_PER_DAY:
            log.warning(f"سقف روزانه ({AI_MAX_PER_DAY}) در حین پردازش تکمیل شد")
            break

        # ── تحلیل بحرانی ──────────────────────────────────────────────────────
        if (
            item.critical
            and critical_done < max_critical
            and not item.pr_analysis
        ):
            log.info(f"🔴 تحلیل بحرانی [{critical_done+1}/{max_critical}]: "
                     f"{item.title[:50]}")
            result = _analyze_critical(model, item)
            if result is not None:
                item.pr_analysis = result
                critical_done   += 1
                ai_used         += 1
                _save_ai_usage(ai_used)   # ← ذخیره فوری
                log.info(f"   ✅ موفق | urgency={result.get('urgency')} | "
                         f"sensitivity={result.get('sensitivity')}")
            time.sleep(AI_RPM_SLEEP)   # رعایت rate limit Gemini

        # ── خلاصه معمولی ──────────────────────────────────────────────────────
        elif (
            not item.critical
            and summary_done < max_summary
            and not item.ai_summary
        ):
            log.info(f"📝 خلاصه [{summary_done+1}/{max_summary}]: "
                     f"{item.title[:50]}")
            summary = _summarize(model, item)
            if summary:
                item.ai_summary = summary
                summary_done   += 1
                ai_used        += 1
                _save_ai_usage(ai_used)   # ← ذخیره فوری
                log.info(f"   ✅ موفق: {summary[:60]}...")
            time.sleep(AI_RPM_SLEEP)

        # ── بررسی توقف هر دو سقف ────────────────────────────────────────────
        if critical_done >= max_critical and summary_done >= max_summary:
            log.info("هر دو سقف ران تکمیل شد")
            break

    log.info(
        f"🤖 AI تمام شد — "
        f"بحرانی:{critical_done}/{max_critical} | "
        f"خلاصه:{summary_done}/{max_summary} | "
        f"کل امروز:{ai_used}/{AI_MAX_PER_DAY}"
    )
    return items, critical_done, summary_done
