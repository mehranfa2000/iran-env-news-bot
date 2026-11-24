"""
analyzer.py — v4.0
تحلیل هوشمند اخبار با Gemini 2.0 Flash
قابلیت‌های جدید:
  - خلاصه‌سازی AI برای همه خبرها (نه فقط بحرانی)
  - تحلیل عمیق ۹ فیلده برای خبرهای بحرانی
  - Rate limiting هوشمند (10 RPM رایگان)
  - Retry با backoff نمایی
  - پشتیبانی از JSON schema ساختاریافته
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import google.generativeai as genai

from src.config import (
    AI_MAX_PER_DAY,
    AI_MAX_PER_RUN,
    AI_MODEL,
    AI_SUMMARY_MAX_PER_RUN,
    AI_TEMPERATURE,
    GEMINI_API_KEY,
    RUN_STATS_FILE,
)
from src.filter import FilteredNewsItem

logger = logging.getLogger("analyzer")

# ═══════════════════════════════════════════════════════════════
# ۱) ساختار تحلیل PR (۹ فیلد)
# ═══════════════════════════════════════════════════════════════
@dataclass
class PRAnalysis:
    sensitivity: str        # حساسیت: خیلی‌بالا / بالا / متوسط / پایین
    sentiment: str          # احساس: منفی / خنثی / مثبت / مختلط
    summary: str            # خلاصه تحلیلی (۲-۳ جمله فارسی)
    risk_factors: list[str] # عوامل خطر (لیست)
    action: str             # اقدام پیشنهادی فوری
    draft_response: str     # پیش‌نویس پاسخ رسمی
    stakeholders: list[str] # ذی‌نفعان اصلی
    urgency: str            # فوریت: فوری / ۲۴ساعت / هفته‌جاری / عادی
    media_risk: str         # ریسک رسانه‌ای: بالا / متوسط / پایین


@dataclass
class AIResult:
    uid: str
    ai_summary: Optional[str]       = None   # خلاصه کوتاه (همه خبرها)
    pr_analysis: Optional[PRAnalysis] = None  # تحلیل کامل (فقط بحرانی)
    model_used: str                 = AI_MODEL
    analyzed_at: str                = ""
    tokens_used: int                = 0

    def to_dict(self) -> dict:
        d = {
            "uid": self.uid,
            "ai_summary": self.ai_summary,
            "model_used": self.model_used,
            "analyzed_at": self.analyzed_at,
            "tokens_used": self.tokens_used,
        }
        if self.pr_analysis:
            d["pr_analysis"] = asdict(self.pr_analysis)
        return d


# ═══════════════════════════════════════════════════════════════
# ۲) شمارنده روزانه (rate limit)
# ═══════════════════════════════════════════════════════════════
class DailyCounter:
    """تعداد تحلیل‌های AI امروز را ردیابی می‌کند."""

    def __init__(self, stats_file: str = RUN_STATS_FILE):
        self.stats_file = Path(stats_file)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if self.stats_file.exists():
                raw = json.loads(self.stats_file.read_text(encoding="utf-8"))
                return raw.get("ai_usage", {})
        except Exception:
            pass
        return {}

    def _save(self, all_stats: dict) -> None:
        try:
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)
            if self.stats_file.exists():
                current = json.loads(self.stats_file.read_text(encoding="utf-8"))
            else:
                current = {}
            current["ai_usage"] = self._data
            current.update(all_stats)
            self.stats_file.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("خطا در ذخیره ai_usage: %s", exc)

    def today_key(self) -> str:
        return date.today().isoformat()

    def used_today(self) -> int:
        return self._data.get(self.today_key(), 0)

    def increment(self, n: int = 1) -> None:
        key = self.today_key()
        self._data[key] = self._data.get(key, 0) + n
        self._save({})

    def can_analyze(self, max_per_day: int = AI_MAX_PER_DAY) -> bool:
        return self.used_today() < max_per_day


# ═══════════════════════════════════════════════════════════════
# ۳) کلاس اصلی تحلیلگر
# ═══════════════════════════════════════════════════════════════
class NewsAnalyzer:
    """تحلیلگر هوش مصنوعی با Gemini 2.0 Flash"""

    # حداقل فاصله بین درخواست‌ها (Rate limit: 10 RPM)
    _MIN_INTERVAL_SECONDS = 7

    def __init__(self):
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=AI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=AI_TEMPERATURE,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        self.counter = DailyCounter()
        self._last_request_time: float = 0.0
        logger.info(
            "🤖 تحلیلگر AI آماده | مدل: %s | مصرف امروز: %d/%d",
            AI_MODEL, self.counter.used_today(), AI_MAX_PER_DAY,
        )

    # ── API ────────────────────────────────────────────────────

    def analyze_batch(
        self, items: list[FilteredNewsItem]
    ) -> dict[str, AIResult]:
        """
        یک دسته خبر را تحلیل می‌کند:
        - خلاصه‌سازی AI: برای همه (تا AI_SUMMARY_MAX_PER_RUN)
        - تحلیل کامل PR: فقط برای بحرانی (تا AI_MAX_PER_RUN)
        خروجی: dict با کلید uid
        """
        results: dict[str, AIResult] = {}

        if not GEMINI_API_KEY:
            logger.warning("⚠️ GEMINI_API_KEY تنظیم نشده — تحلیل AI غیرفعال")
            return results

        if not self.counter.can_analyze():
            logger.warning(
                "⛔ سقف روزانه AI رسیده (%d/%d)", self.counter.used_today(), AI_MAX_PER_DAY
            )
            return results

        # جداسازی بحرانی از معمولی
        critical_items = [i for i in items if i.critical]
        normal_items   = [i for i in items if not i.critical]

        summary_count   = 0
        full_analysis   = 0

        # ۱) تحلیل کامل برای بحرانی (با اولویت)
        for item in critical_items:
            if full_analysis >= AI_MAX_PER_RUN:
                break
            if not self.counter.can_analyze():
                break
            result = self._full_analysis(item)
            if result:
                results[item.uid] = result
                full_analysis += 1
                self.counter.increment()

        # ۲) خلاصه‌سازی برای بقیه (تا سقف)
        remaining_budget = AI_SUMMARY_MAX_PER_RUN - len(results)
        all_for_summary = [i for i in normal_items if i.uid not in results]

        for item in all_for_summary[:remaining_budget]:
            if not self.counter.can_analyze():
                break
            result = self._summarize(item)
            if result:
                results[item.uid] = result
                summary_count += 1
                self.counter.increment()

        logger.info(
            "✅ تحلیل AI: %d تحلیل کامل + %d خلاصه | مصرف روزانه: %d/%d",
            full_analysis, summary_count,
            self.counter.used_today(), AI_MAX_PER_DAY,
        )
        return results

    # ── تحلیل کامل ────────────────────────────────────────────

    def _full_analysis(self, item: FilteredNewsItem) -> Optional[AIResult]:
        """تحلیل ۹ فیلده PR برای خبر بحرانی"""
        prompt = self._build_full_prompt(item)
        raw = self._call_gemini(prompt, item.uid)
        if not raw:
            return None

        try:
            data = json.loads(raw)
            pr = PRAnalysis(
                sensitivity   = data.get("sensitivity",   "متوسط"),
                sentiment      = data.get("sentiment",      "خنثی"),
                summary        = data.get("summary",        ""),
                risk_factors   = data.get("risk_factors",   []),
                action         = data.get("action",         ""),
                draft_response = data.get("draft_response", ""),
                stakeholders   = data.get("stakeholders",   []),
                urgency        = data.get("urgency",        "عادی"),
                media_risk     = data.get("media_risk",     "پایین"),
            )
            return AIResult(
                uid=item.uid,
                ai_summary=pr.summary,
                pr_analysis=pr,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("❌ parse تحلیل کامل شکست خورد [%s]: %s", item.uid, exc)
            return None

    def _summarize(self, item: FilteredNewsItem) -> Optional[AIResult]:
        """خلاصه‌سازی کوتاه برای خبر معمولی"""
        prompt = self._build_summary_prompt(item)
        raw = self._call_gemini(prompt, item.uid)
        if not raw:
            return None

        try:
            data = json.loads(raw)
            summary = data.get("summary", "").strip()
            if not summary:
                return None
            return AIResult(
                uid=item.uid,
                ai_summary=summary,
                pr_analysis=None,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("❌ parse خلاصه شکست خورد [%s]: %s", item.uid, exc)
            return None

    # ── Prompt Builder ─────────────────────────────────────────

    @staticmethod
    def _build_full_prompt(item: FilteredNewsItem) -> str:
        return f"""
تو یک متخصص ارشد روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستی.
این خبر **بحرانی** است و نیاز به تحلیل فوری دارد.

**عنوان خبر:** {item.title}
**خلاصه:** {item.summary[:600]}
**منبع:** {item.source}
**دسته:** {item.category.name}

یک JSON معتبر با دقیقاً این ۹ کلید برگردان (همه به فارسی):

{{
  "sensitivity":    "یکی از: خیلی‌بالا / بالا / متوسط / پایین",
  "sentiment":      "یکی از: منفی / خنثی / مثبت / مختلط",
  "summary":        "خلاصه تحلیلی ۲-۳ جمله برای مدیران ارشد",
  "risk_factors":   ["عامل خطر ۱", "عامل خطر ۲", "..."],
  "action":         "اقدام فوری پیشنهادی (یک جمله)",
  "draft_response": "پیش‌نویس پاسخ رسمی سازمان (۲-۳ جمله رسمی)",
  "stakeholders":   ["ذی‌نفع ۱", "ذی‌نفع ۲", "..."],
  "urgency":        "یکی از: فوری / ۲۴ساعت / هفته‌جاری / عادی",
  "media_risk":     "یکی از: بالا / متوسط / پایین"
}}

فقط JSON خالص. بدون توضیح اضافه.
""".strip()

    @staticmethod
    def _build_summary_prompt(item: FilteredNewsItem) -> str:
        return f"""
تو یک کارشناس خبری سازمان حفاظت محیط‌زیست ایران هستی.

**عنوان:** {item.title}
**متن:** {item.summary[:400]}

یک JSON با یک کلید برگردان:
{{
  "summary": "خلاصه ۱-۲ جمله حرفه‌ای فارسی از این خبر"
}}

فقط JSON خالص.
""".strip()

    # ── HTTP Call با Retry ─────────────────────────────────────

    def _call_gemini(
        self, prompt: str, uid: str, max_retries: int = 3
    ) -> Optional[str]:
        """فراخوانی Gemini با rate-limiting و retry"""
        for attempt in range(1, max_retries + 1):
            # Rate limiting
            elapsed = time.time() - self._last_request_time
            if elapsed < self._MIN_INTERVAL_SECONDS:
                wait = self._MIN_INTERVAL_SECONDS - elapsed
                logger.debug("⏳ Rate limit: %.1f ثانیه صبر", wait)
                time.sleep(wait)

            try:
                self._last_request_time = time.time()
                response = self.model.generate_content(prompt)
                text = response.text.strip()

                # پاک‌سازی markdown اگر وجود داشت
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()

                logger.debug("✅ Gemini پاسخ داد [%s] (تلاش %d)", uid[:8], attempt)
                return text

            except Exception as exc:
                wait = 2 ** attempt  # backoff نمایی: 2, 4, 8
                logger.warning(
                    "⚠️ Gemini خطا [%s] تلاش %d/%d: %s — %.0f ثانیه صبر",
                    uid[:8], attempt, max_retries, exc, wait,
                )
                if attempt < max_retries:
                    time.sleep(wait)

        logger.error("❌ Gemini پس از %d تلاش شکست خورد [%s]", max_retries, uid[:8])
        return None


# ── تابع سطح بالا ─────────────────────────────────────────────
def analyze_news(items: list[FilteredNewsItem]) -> dict[str, AIResult]:
    return NewsAnalyzer().analyze_batch(items)
