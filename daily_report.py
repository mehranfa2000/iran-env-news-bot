#!/usr/bin/env python3
"""
daily_report.py — گزارش روزانه هوشمند محیط‌زیست
نسخه: 4.2.0
اجرا: هر شب ساعت ۲۳:۳۰ به وقت تهران (UTC 20:00)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jdatetime

# ─── مسیرها ───────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
NEWS_PATH    = ROOT / "data" / "news.json"
DAILY_PATH   = ROOT / "data" / "daily_analysis.json"
STATS_PATH   = ROOT / "data" / "run_stats.json"
LOG_PATH     = ROOT / "data" / "daily_report.log"

# ─── ثابت‌ها ──────────────────────────────────────────────────────────────────
AI_MODEL        = os.environ.get("AI_MODEL", "gemini-3.6-flash")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
WINDOW_HOURS    = 24          # پنجره زمانی گزارش (ساعت)
MAX_CRITICAL_IN_REPORT = 10   # حداکثر خبر بحرانی در گزارش

CATEGORY_FA: dict[str, str] = {
    "air_water_soil":  "آلودگی هوا، آب و خاک",
    "wildlife":        "حیات وحش و تنوع زیستی",
    "water_wetlands":  "تالاب‌ها، دریاها و منابع آب",
    "climate":         "تغییر اقلیم و بحران‌های طبیعی",
    "forests":         "جنگل‌ها، مراتع و منابع طبیعی",
    "policy":          "سیاست‌ها، قوانین و سازمان",
    "sustainable":     "توسعه پایدار و انرژی پاک",
}


# ─── Logging ──────────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("daily_report")
    logger.setLevel(logging.INFO)
    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    # File
    try:
        import logging.handlers
        fh = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    return logger


log = _setup_logging()


# ─── بارگذاری داده ────────────────────────────────────────────────────────────
def _load_json(path: Path, default: Any = None) -> Any:
    """بارگذاری امن JSON با fallback."""
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"خطا در خواندن {path.name}: {e}")
    return default if default is not None else {}


def _save_json(path: Path, data: Any) -> bool:
    """ذخیره JSON با مدیریت خطا."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        log.error(f"خطا در نوشتن {path.name}: {e}")
        return False


# ─── فیلتر اخبار پنجره زمانی ─────────────────────────────────────────────────
def _filter_window(
    all_news: list[dict],
    hours: int = WINDOW_HOURS,
) -> list[dict]:
    """
    اخبار درون پنجره زمانی را برمی‌گرداند.
    برای اخبار بدون published_at معتبر → رد می‌شود.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result: list[dict] = []

    for item in all_news:
        try:
            pub_str = item.get("published_at", "")
            if not pub_str:
                continue
            pub = datetime.fromisoformat(pub_str)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                result.append(item)
        except Exception:
            continue

    return result


# ─── محاسبه آمار ──────────────────────────────────────────────────────────────
def _compute_stats(items: list[dict]) -> dict:
    """
    آمار جامع از اخبار پنجره زمانی:
    - تعداد کل، بحرانی، ارسال‌شده
    - توزیع دسته‌بندی و منبع
    - میانگین امتیاز
    - خبرهای بحرانی (با pr_analysis)
    """
    if not items:
        return {
            "total": 0,
            "critical": 0,
            "sent": 0,
            "avg_score": 0.0,
            "category_breakdown": {},
            "source_breakdown": {},
            "top_critical": [],
            "has_data": False,
        }

    total    = len(items)
    critical = sum(1 for n in items if n.get("critical"))
    sent     = sum(1 for n in items if n.get("sent"))
    scores   = [n.get("score", 0) for n in items if isinstance(n.get("score"), (int, float))]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    cat_raw  = Counter(n.get("category", "unknown") for n in items)
    cat_fa   = {
        CATEGORY_FA.get(k, k): v
        for k, v in cat_raw.most_common()
    }

    src_counts = dict(Counter(n.get("source", "نامشخص") for n in items).most_common(10))

    # خبرهای بحرانی برای گزارش (با بیشترین امتیاز)
    critical_items = sorted(
        [n for n in items if n.get("critical")],
        key=lambda x: x.get("score", 0),
        reverse=True,
    )[:MAX_CRITICAL_IN_REPORT]

    top_critical = [
        {
            "title":       n.get("title", ""),
            "source":      n.get("source", ""),
            "category_fa": CATEGORY_FA.get(n.get("category", ""), n.get("category", "")),
            "score":       n.get("score", 0),
            "shamsi_date": n.get("shamsi_date", ""),
            "link":        n.get("link", ""),
            "pr_summary":  (
                n.get("pr_analysis", {}).get("summary", "")
                if isinstance(n.get("pr_analysis"), dict)
                else ""
            ),
            "urgency": (
                n.get("pr_analysis", {}).get("urgency", "")
                if isinstance(n.get("pr_analysis"), dict)
                else ""
            ),
        }
        for n in critical_items
    ]

    return {
        "total":              total,
        "critical":           critical,
        "sent":               sent,
        "avg_score":          avg_score,
        "category_breakdown": cat_fa,
        "source_breakdown":   src_counts,
        "top_critical":       top_critical,
        "has_data":           True,
    }


# ─── خلاصه اجرایی با AI ───────────────────────────────────────────────────────
def _ai_executive_summary(stats: dict) -> str:
    """
    با Gemini یک خلاصه اجرایی فارسی می‌سازد.
    اگر API key نبود یا model 404 → متن fallback.
    """
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY تنظیم نشده — خلاصه AI رد شد")
        return _fallback_summary(stats)

    # آماده‌سازی داده‌های خلاصه برای prompt
    top_cats = list(stats.get("category_breakdown", {}).items())[:3]
    cat_text = "، ".join(f"{k} ({v} خبر)" for k, v in top_cats) if top_cats else "نامشخص"

    critical_titles = [
        f"- {c['title'][:80]} (منبع: {c['source']})"
        for c in stats.get("top_critical", [])[:5]
    ]
    critical_text = "\n".join(critical_titles) if critical_titles else "خبر بحرانی ثبت نشد"

    prompt = f"""تو تحلیلگر ارشد روابط‌عمومی سازمان حفاظت محیط‌زیست ایران هستی.

آمار پایش اخبار امروز (۲۴ ساعت گذشته):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• کل اخبار پایش‌شده: {stats['total']}
• اخبار بحرانی: {stats['critical']}
• اخبار ارسال‌شده: {stats['sent']}
• میانگین امتیاز اخبار: {stats['avg_score']}
• دسته‌های غالب: {cat_text}

مهم‌ترین اخبار بحرانی امروز:
{critical_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

یک گزارش اجرایی کوتاه (۳ تا ۵ جمله) به فارسی رسمی بنویس که شامل موارد زیر باشد:
۱. وضعیت کلی محیط‌زیست امروز
۲. مهم‌ترین حوزه‌های خبری
۳. توصیه‌ای برای تیم روابط‌عمومی
فقط متن گزارش، بدون هیچ توضیح یا مقدمه اضافه."""

    for attempt in range(2):
        try:
            import google.generativeai as genai

            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(AI_MODEL)
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.4, "max_output_tokens": 400},
                request_options={"timeout": 30},
            )
            text = response.text.strip()
            if text:
                log.info(f"✅ خلاصه AI موفق ({len(text)} کاراکتر)")
                return text

        except Exception as e:
            err = str(e).lower()
            if "404" in err and any(w in err for w in ["not found", "no longer", "deprecated"]):
                log.critical(f"🚫 مدل AI مرده (404): {e}")
                break
            log.warning(f"خطا در AI (attempt {attempt + 1}/2): {e}")
            if attempt == 0:
                time.sleep(5)

    return _fallback_summary(stats)


def _fallback_summary(stats: dict) -> str:
    """خلاصه متنی بدون AI — همیشه کار می‌کند."""
    if not stats.get("has_data"):
        return "امروز هیچ خبر محیط‌زیستی در پنجره ۲۴ ساعته ثبت نشده است."

    top_cat = next(iter(stats.get("category_breakdown", {})), "نامشخص")
    return (
        f"در ۲۴ ساعت گذشته مجموعاً {stats['total']} خبر محیط‌زیستی پایش شد "
        f"که {stats['critical']} مورد بحرانی بودند. "
        f"بیشترین اخبار در حوزه «{top_cat}» منتشر شد. "
        f"میانگین امتیاز اخبار {stats['avg_score']} بود. "
        f"خلاصه هوشمند در این اجرا در دسترس نبود."
    )


# ─── ساخت گزارش نهایی ─────────────────────────────────────────────────────────
def _build_report(stats: dict, ai_summary: str) -> dict:
    """گزارش کامل روزانه را می‌سازد."""
    now_utc   = datetime.now(timezone.utc)
    shamsi    = jdatetime.datetime.fromgregorian(datetime=now_utc)

    return {
        # ─── متادیتا ───
        "schema_version":    "4.2",
        "generated_at_utc":  now_utc.isoformat(),
        "date_shamsi":       shamsi.strftime("%Y/%m/%d"),
        "date_gregorian":    now_utc.strftime("%Y-%m-%d"),
        "window_hours":      WINDOW_HOURS,

        # ─── خلاصه AI ───
        "ai_executive_summary": ai_summary,
        "ai_model_used":        AI_MODEL if GEMINI_API_KEY else "none",

        # ─── آمار ───
        "statistics": {
            "total_news":         stats["total"],
            "critical_news":      stats["critical"],
            "sent_news":          stats["sent"],
            "avg_score":          stats["avg_score"],
            "category_breakdown": stats["category_breakdown"],
            "source_breakdown":   stats["source_breakdown"],
        },

        # ─── خبرهای بحرانی ───
        "top_critical_news": stats["top_critical"],
    }


# ─── نقطه ورود ────────────────────────────────────────────────────────────────
def main() -> int:
    """
    Returns:
        0 موفق
        1 خطای غیرقابل بازیابی
    """
    t0 = time.monotonic()
    log.info("=" * 60)
    log.info("📊 گزارش روزانه هوشمند محیط‌زیست — نسخه 4.2")
    log.info(f"📅 {jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')}")
    log.info("=" * 60)

    # ۱. بارگذاری اخبار
    all_news = _load_json(NEWS_PATH, default=[])
    if not isinstance(all_news, list):
        log.error("news.json فرمت نامعتبر دارد")
        all_news = []
    log.info(f"📂 {len(all_news)} خبر در کل بارگذاری شد")

    # ۲. فیلتر پنجره ۲۴ ساعته
    window_news = _filter_window(all_news, hours=WINDOW_HOURS)
    log.info(f"🕐 {len(window_news)} خبر در ۲۴ ساعت گذشته")

    # ۳. محاسبه آمار
    stats = _compute_stats(window_news)
    log.info(
        f"📊 آمار: کل={stats['total']} | "
        f"بحرانی={stats['critical']} | "
        f"ارسال‌شده={stats['sent']} | "
        f"میانگین‌امتیاز={stats['avg_score']}"
    )

    # ۴. خلاصه AI
    log.info("🤖 تولید خلاصه اجرایی با AI...")
    ai_summary = _ai_executive_summary(stats)

    # ۵. ساخت و ذخیره گزارش
    report = _build_report(stats, ai_summary)
    if not _save_json(DAILY_PATH, report):
        log.error("❌ ذخیره گزارش روزانه ناموفق بود")
        return 1

    elapsed = time.monotonic() - t0
    log.info(f"✅ گزارش روزانه ذخیره شد — {elapsed:.1f}s")
    log.info(f"📄 مسیر: {DAILY_PATH}")
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
