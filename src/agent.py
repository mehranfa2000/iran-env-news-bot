# src/agent.py
"""
ساختارهای داده‌ای اصلی، مدیریت ذخیره‌سازی و آمار اجرا
نسخه ۴.۰
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

import jdatetime

from config import (
    NEWS_FILE,
    RUN_STATS_FILE,
    MAX_STORED_NEWS,
    MAX_RUN_STATS,
    DATA_DIR,
)

logger = logging.getLogger("agent")


# ══════════════════════════════════════════════════════════════════
# ساختار داده خبر
# ══════════════════════════════════════════════════════════════════

@dataclass
class PRAnalysis:
    """تحلیل ۹ فیلدی روابط‌عمومی برای خبرهای بحرانی"""
    sensitivity: str    = ""   # حساسیت: کم / متوسط / بالا / بحرانی
    sentiment: str      = ""   # احساس: مثبت / منفی / خنثی / مختلط
    summary: str        = ""   # خلاصه تحلیلی
    risk_factors: str   = ""   # عوامل ریسک
    action: str         = ""   # اقدام پیشنهادی
    draft_response: str = ""   # پیش‌نویس پاسخ رسانه‌ای
    stakeholders: str   = ""   # ذی‌نفعان
    urgency: str        = ""   # فوریت: فوری / ۲۴ ساعت / هفتگی
    media_risk: str     = ""   # ریسک رسانه‌ای: کم / متوسط / بالا


@dataclass
class NewsItem:
    """یک خبر محیط‌زیستی"""
    uid: str                        # sha256(link)[:16]
    title: str
    link: str
    source: str
    published_at: str               # ISO 8601 UTC
    shamsi_date: str                # مثال: ۱۴۰۴/۰۳/۱۲
    shamsi_time: str                # مثال: ۱۴:۳۰
    summary: str                    = ""
    image_url: str                  = ""
    category: str                   = "policy"
    score: int                      = 0
    is_critical: bool               = False
    sent_telegram: bool             = False
    sent_bale: bool                 = False
    ai_summary: str                 = ""
    pr_analysis: Optional[PRAnalysis] = None

    @staticmethod
    def make_uid(link: str) -> str:
        return hashlib.sha256(link.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "NewsItem":
        pr = d.pop("pr_analysis", None)
        item = NewsItem(**d)
        if pr:
            item.pr_analysis = PRAnalysis(**pr)
        return item


def make_shamsi(dt: Optional[datetime] = None) -> tuple[str, str]:
    """تبدیل datetime به تاریخ و زمان شمسی"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    date_str = f"{j.year:04d}/{j.month:02d}/{j.day:02d}"
    time_str = f"{j.hour:02d}:{j.minute:02d}"
    return date_str, time_str


# ══════════════════════════════════════════════════════════════════
# مدیریت ذخیره‌سازی
# ══════════════════════════════════════════════════════════════════

class StorageManager:
    """ذخیره و بارگذاری اخبار از data/news.json"""

    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._news: dict[str, NewsItem] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(NEWS_FILE):
            logger.info("📂 فایل اخبار موجود نیست — شروع خالی")
            return
        try:
            with open(NEWS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("news", [])
            for d in items:
                try:
                    item = NewsItem.from_dict(d)
                    self._news[item.uid] = item
                except Exception as e:
                    logger.warning("⚠️ خطا در بارگذاری خبر: %s", e)
            logger.info("📥 %d خبر بارگذاری شد", len(self._news))
        except Exception as e:
            logger.error("❌ خطا در خواندن news.json: %s", e)

    def save(self) -> None:
        """ذخیره اخبار — حداکثر MAX_STORED_NEWS خبر جدیدتر"""
        sorted_items = sorted(
            self._news.values(),
            key=lambda x: x.published_at,
            reverse=True,
        )[:MAX_STORED_NEWS]

        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "updated_at": now_iso,
            "total_count": len(sorted_items),
            "news": [item.to_dict() for item in sorted_items],
        }
        try:
            with open(NEWS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info("💾 %d خبر ذخیره شد", len(sorted_items))
        except Exception as e:
            logger.error("❌ خطا در ذخیره news.json: %s", e)

    def exists(self, uid: str) -> bool:
        return uid in self._news

    def add(self, item: NewsItem) -> None:
        self._news[item.uid] = item

    def update(self, item: NewsItem) -> None:
        self._news[item.uid] = item

    def get(self, uid: str) -> Optional[NewsItem]:
        return self._news.get(uid)

    def all_items(self) -> list[NewsItem]:
        return list(self._news.values())

    def unsent_items(self) -> list[NewsItem]:
        return [i for i in self._news.values() if not i.sent_telegram and not i.sent_bale]


# ══════════════════════════════════════════════════════════════════
# آمار اجرا
# ══════════════════════════════════════════════════════════════════

@dataclass
class RunStats:
    """آمار یک دور اجرای سیستم"""
    run_id: str         = ""
    started_at: str     = ""
    finished_at: str    = ""
    feeds_checked: int  = 0
    items_fetched: int  = 0
    items_filtered: int = 0
    items_sent: int     = 0
    ai_used: int        = 0
    errors: int         = 0
    duration_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunStatsManager:
    """ذخیره و بارگذاری آمار اجراها"""

    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._stats: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(RUN_STATS_FILE):
            return
        try:
            with open(RUN_STATS_FILE, encoding="utf-8") as f:
                self._stats = json.load(f).get("runs", [])
        except Exception as e:
            logger.warning("⚠️ خطا در بارگذاری run_stats.json: %s", e)

    def add(self, stats: RunStats) -> None:
        self._stats.append(stats.to_dict())
        self._stats = self._stats[-MAX_RUN_STATS:]

    def save(self) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "runs": self._stats,
        }
        try:
            with open(RUN_STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("❌ خطا در ذخیره run_stats.json: %s", e)
