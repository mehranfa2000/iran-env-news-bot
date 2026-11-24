# daily_analysis.py
"""
تولید گزارش تحلیلی روزانه با هوش مصنوعی
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "src")

import google.generativeai as genai
import jdatetime

from config import GEMINI_API_KEY, AI_MODEL, NEWS_FILE, ANALYSIS_FILE, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_analysis")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    _model = genai.GenerativeModel(AI_MODEL)
else:
    _model = None
    logger.error("GEMINI_API_KEY تنظیم نشده")
    sys.exit(1)


def load_recent_news(hours: int = 24) -> list[dict]:
    if not os.path.exists(NEWS_FILE):
        return []
    with open(NEWS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("news", [])[:50]


def generate_daily_report(news_items: list[dict]) -> dict:
    if not news_items:
        return {"error": "اخبار کافی یافت نشد"}

    titles = "\n".join(
        f"- [{i['category']}] {i['title']} ({i['source']})"
        for i in news_items[:30]
    )

    prompt = f"""
شما تحلیل‌گر ارشد روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستید.
بر اساس اخبار زیر یک گزارش تحلیلی جامع روزانه تهیه کنید.

اخبار امروز:
{titles}

پاسخ را به صورت JSON با ساختار زیر برگردانید:
{{
  "executive_summary": "خلاصه اجرایی برای مدیران ارشد (200 کلمه)",
  "top_issues": ["مهم‌ترین مسئله 1", "مهم‌ترین مسئله 2", "مهم‌ترین مسئله 3"],
  "risk_level": "کم | متوسط | بالا | بحرانی",
  "category_analysis": {{
    "air_water_soil": "تحلیل آلودگی",
    "wildlife": "تحلیل حیات وحش",
    "water_wetlands": "تحلیل آب و تالاب",
    "climate": "تحلیل اقلیم",
    "forests": "تحلیل جنگل",
    "policy": "تحلیل سیاست",
    "sustainable": "تحلیل توسعه پایدار"
  }},
  "recommendations": ["توصیه 1", "توصیه 2", "توصیه 3"],
  "media_tone": "مثبت | منفی | خنثی | مختلط",
  "public_concern_level": "کم | متوسط | بالا",
  "action_items": ["اقدام فوری 1", "اقدام فوری 2"]
}}
"""
    try:
        resp = _model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=3000,
            ),
            request_options={"timeout": 60},
        )
        return json.loads(resp.text)
    except Exception as e:
        logger.error("خطای Gemini: %s", e)
        return {"error": str(e)}


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    logger.info("📊 شروع تولید گزارش روزانه")
    news = load_recent_news()
    logger.info("📰 %d خبر بارگذاری شد", len(news))

    report = generate_daily_report(news)

    now = datetime.now(timezone.utc)
    j = jdatetime.datetime.fromgregorian(datetime=now)
    shamsi = f"{j.year:04d}/{j.month:02d}/{j.day:02d}"

    payload = {
        "generated_at": now.isoformat(),
        "shamsi_date": shamsi,
        "news_count": len(news),
        "report": report,
    }

    with open(ANALYSIS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info("✅ گزارش روزانه ذخیره شد: %s", ANALYSIS_FILE)


if __name__ == "__main__":
    main()
