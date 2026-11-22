# ============================================================
#  src/analyzer.py — دستیار AI روابط عمومی
#  مدل: Gemini 3.8 Flash (رایگان)
#  خروجی ساختارمند با Pydantic
# ============================================================

import json
import time
from typing import Optional
from pydantic import BaseModel, Field

from src.config import GEMINI_API_KEY, AI_MODEL, AI_ENABLED, AI_TIMEOUT


# ── Schema خروجی AI ──────────────────────────────────────────

class AIAnalysis(BaseModel):
    """ساختار تحلیل AI برای هر خبر"""
    sensitivity: str = Field(
        description="سطح حساسیت: critical / high / normal / positive"
    )
    sensitivity_label: str = Field(
        description="برچسب فارسی سطح حساسیت"
    )
    sentiment: str = Field(
        description="لحن خبر: negative / neutral / positive"
    )
    sentiment_label: str = Field(
        description="برچسب فارسی لحن خبر"
    )
    summary: str = Field(
        description="خلاصه تحلیلی ۲-۳ جمله‌ای"
    )
    suggested_action: str = Field(
        description="پیشنهاد واکنش روابط عمومی"
    )
    draft_response: str = Field(
        description="پیش‌نویس پاسخ رسمی روابط عمومی"
    )
    stakeholders: list[str] = Field(
        description="لیست ذی‌نفعان و سازمان‌های مرتبط"
    )
    response_urgency: str = Field(
        description="فوریت پاسخ: فوری / ۲۴ ساعت / هفتگی / نیازی نیست"
    )


# ── System Prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """تو دستیار تحلیل رسانه‌ای روابط عمومی سازمان حفاظت محیط زیست جمهوری اسلامی ایران هستی.

وظیفه تو تحلیل هر خبر محیط زیستی و ارائه موارد زیر است:

۱. سطح حساسیت (sensitivity): یکی از مقادیر زیر:
   - critical: خبر بحرانی که نیاز به واکنش فوری دارد (مثل فاجعه زیست‌محیطی، تلفات حیات وحش، آلودگی شدید)
   - high: خبر حساس که نیاز به رصد و آماده‌باش دارد (مثل آلودگی هوا، تخلفات، شکار غیرمجاز)
   - normal: خبر عادی و اطلاع‌رسانی (مثل گزارش‌ها، آمار، رویدادها)
   - positive: خبر مثبت (مثل احیا، بهبود، موفقیت، افتتاح)

۲. برچسب فارسی (sensitivity_label): 🔴 بحرانی / 🟡 حساس / 🔵 عادی / 🟢 مثبت

۳. لحن خبر (sentiment): negative / neutral / positive
   - negative: انتقادی یا منفی نسبت به عملکرد سازمان
   - neutral: خنثی و خبری
   - positive: مثبت و تقدیرآمیز

۴. برچسب فارسی لحن (sentiment_label): منفی / خنثی / مثبت

۵. خلاصه تحلیلی (summary): ۲-۳ جمله تحلیل واقعی از دید روابط عمومی

۶. پیشنهاد واکنش (suggested_action): دقیقاً چه اقدامی باید انجام شود

۷. پیش‌نویس پاسخ رسمی (draft_response): یک متن ۳-۵ جمله‌ای رسمی و محترمانه که روابط عمومی بتواند مستقیماً استفاده کند

۸. ذی‌نفعان (stakeholders): لیست سازمان‌ها و نهادهای نام‌برده‌شده در خبر

۹. فوریت پاسخ (response_urgency): فوری / ۲۴ ساعت / هفتگی / نیازی نیست

قوانین:
- لحن رسمی و محترمانه
- همیشه از منظر دفاع از محیط زیست
- هرگز اظهارنظر سیاسی نکن
- به زبان فارسی پاسخ بده
- پاسخ‌ها باید با سیاست‌های رسمی سازمان حفاظت محیط زیست همخوان باشد"""


# ── تابع تحلیل ────────────────────────────────────────────────

def analyze_article(article: dict) -> dict | None:
    """
    تحلیل یک خبر با Gemini AI

    Returns:
        دیکشنری ai_analysis یا None در صورت خطا
    """
    if not AI_ENABLED:
        return None

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)

        title   = article.get("title", "")
        summary = article.get("summary", "")
        source  = article.get("source", "")
        cat     = article.get("category", "")

        prompt = f"""خبر زیر را تحلیل کن:

عنوان: {title}
خلاصه: {summary}
منبع: {source}
دسته‌بندی: {cat}"""

        response = client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": AIAnalysis,
                "system_instruction": SYSTEM_PROMPT,
            },
        )

        # خروجی ساختارمند — Pydantic parsed
        if hasattr(response, 'parsed') and response.parsed:
            result = response.parsed
            return result.model_dump()

        # اگر parsed نبود، از text استفاده کن
        if response.text:
            return json.loads(response.text)

        return None

    except Exception as e:
        print(f"    ⚠️  خطای AI: {e}")
        return None


def analyze_batch(articles: list) -> list:
    """
    تحلیل دسته‌ای اخبار

    Args:
        articles: لیست اخبار فیلترشده

    Returns:
        همان لیست با افزودن فیلد ai_analysis
    """
    if not AI_ENABLED:
        print("⚠️  کلید Gemini تنظیم نشده — تحلیل AI رد می‌شود")
        return articles

    print(f"🧠 شروع تحلیل AI برای {len(articles)} خبر...")

    success = 0
    fail    = 0

    for i, article in enumerate(articles, 1):
        title = article.get("title", "")[:50]
        print(f"  🧠 [{i}/{len(articles)}] {title}...")

        analysis = analyze_article(article)

        if analysis:
            article["ai_analysis"] = analysis
            success += 1
            print(f"    ✅ {analysis.get('sensitivity_label', '—')}")
        else:
            # اگر AI کار نکرد، تحلیل ساده بر اساس کلیدواژه
            article["ai_analysis"] = _fallback_analysis(article)
            fail += 1
            print(f"    ⚡ fallback")

        # رعایت rate limit: 10 درخواست در دقیقه
        if i % 9 == 0:
            print(f"    ⏳ توقف ۶۵ ثانیه (rate limit)...")
            time.sleep(65)
        else:
            time.sleep(2)

    print(f"🧠 نتیجه: {success} موفق، {fail} fallback")
    return articles


def _fallback_analysis(article: dict) -> dict:
    """تحلیل ساده بر اساس کلیدواژه (وقتی AI در دسترس نیست)"""
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()

    critical_words = ['بحران', 'فاجعه', 'اضطرار', 'خطرناک', 'مرگ', 'تلف',
                      'آتش‌سوزی', 'سیل', 'زلزله', 'فوری', 'نابودی']
    positive_words = ['احیا', 'بهبود', 'موفقیت', 'افتتاح', 'کاهش آلودگی',
                      'حفاظت موفق', 'رکورد', 'همکاری', 'مشارکت']
    high_words     = ['آلودگی', 'تخریب', 'خشک شدن', 'شکار', 'قاچاق',
                      'تخلف', 'جریمه', 'اعتراض', 'نگران']

    if any(w in text for w in critical_words):
        return {
            "sensitivity": "critical",
            "sensitivity_label": "🔴 بحرانی",
            "sentiment": "negative",
            "sentiment_label": "منفی",
            "summary": "این خبر نیاز به بررسی فوری دارد.",
            "suggested_action": "بررسی فوری و آماده‌سازی بیانیه",
            "draft_response": "",
            "stakeholders": [],
            "response_urgency": "فوری",
        }
    elif any(w in text for w in positive_words):
        return {
            "sensitivity": "positive",
            "sensitivity_label": "🟢 مثبت",
            "sentiment": "positive",
            "sentiment_label": "مثبت",
            "summary": "این خبر مثبت است و فرصت تقدیر دارد.",
            "suggested_action": "انتشار و تقدیر",
            "draft_response": "",
            "stakeholders": [],
            "response_urgency": "نیازی نیست",
        }
    elif any(w in text for w in high_words):
        return {
            "sensitivity": "high",
            "sensitivity_label": "🟡 حساس",
            "sentiment": "neutral",
            "sentiment_label": "خنثی",
            "summary": "این خبر نیاز به رصد دارد.",
            "suggested_action": "رصد و آماده‌باش",
            "draft_response": "",
            "stakeholders": [],
            "response_urgency": "۲۴ ساعت",
        }
    else:
        return {
            "sensitivity": "normal",
            "sensitivity_label": "🔵 عادی",
            "sentiment": "neutral",
            "sentiment_label": "خنثی",
            "summary": "خبر اطلاع‌رسانی عادی.",
            "suggested_action": "ثبت و آرشیو",
            "draft_response": "",
            "stakeholders": [],
            "response_urgency": "نیازی نیست",
        }
