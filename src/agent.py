"""
agent.py — v4.0
هسته مرکزی ایجنت هوشمند:
  - StorageManager: ذخیره/بازیابی اخبار در data/news.json
  - RunStats: آمار هر اجرا برای داشبورد
  - NewsItem: مدل یکپارچه خبر (ذخیره‌سازی + ارسال)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jdatetime

from src.config import (
    MAX_STORED_NEWS,
    NEWS_FILE,
    RUN_STATS_FILE,
)
from src.filter import FilteredNewsItem
from src.analyzer import AIResult

logger = logging.getLogger("agent")


# ═══════════════════════════════════════════════════════════════
# ۱) مدل NewsItem (فرمت ذخیره‌سازی نهایی)
# ═══════════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    uid: str
    title: str
    summary: str
    link: str
    source: str
    published_iso: str              # ISO 8601 UTC
    published_shamsi: str           # مثال: ۱۴ آذر ۱۴۰۵
    published_time: str             # مثال: ۱۴:۳۵
    image_url: Optional[str]
    category_id: str
    category_name: str
    category_emoji: str
    category_color: str
    score: int
    critical: bool
    matched_keywords: list[str]
    ai_summary: Optional[str]       = None
    pr_analysis: Optional[dict]     = None
    sent_telegram: bool             = False
    sent_bale: bool                 = False
    created_at: str                 = ""    # زمان ذخیره در سیستم

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_filtered(
        cls,
        item: FilteredNewsItem,
        ai_result: Optional[AIResult] = None,
    ) -> "NewsItem":
        """ساخت NewsItem از FilteredNewsItem + AIResult"""
        # تبدیل زمان
        dt = item.published_dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        try:
            jdt = jdatetime.datetime.fromgregorian(datetime=dt)
            months = [
                "","فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
                "مهر","آبان","آذر","دی","بهمن","اسفند",
            ]
            shamsi_date = f"{jdt.day} {months[jdt.month]} {jdt.year}"
            shamsi_time = f"{jdt.hour:02d}:{jdt.minute:02d}"
        except Exception:
            shamsi_date = "نامشخص"
            shamsi_time = "نامشخص"

        ai_sum = None
        pr_dict = None
        if ai_result:
            ai_sum = ai_result.ai_summary
            if ai_result.pr_analysis:
                from dataclasses import asdict as _asdict
                pr_dict = _asdict(ai_result.pr_analysis)

        return cls(
            uid=item.uid,
            title=item.title,
            summary=item.summary,
            link=item.link,
            source=item.source,
            published_iso=dt.isoformat(),
            published_shamsi=shamsi_date,
            published_time=shamsi_time,
            image_url=item.image_url,
            category_id=item.category.id,
            category_name=item.category.name,
            category_emoji=item.category.emoji,
            category_color=item.category.color,
            score=item.score,
            critical=item.critical,
            matched_keywords=item.matched_keywords,
            ai_summary=ai_sum,
            pr_analysis=pr_dict,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ═══════════════════════════════════════════════════════════════
# ۲) مدیریت ذخیره‌سازی
# ═══════════════════════════════════════════════════════════════
class StorageManager:
    """
    مدیریت data/news.json:
      - بارگذاری اخبار قبلی
      - اضافه کردن اخبار جدید
      - جلوگیری از تکرار (بر اساس uid)
      - محدود کردن تعداد اخبار (MAX_STORED_NEWS)
      - ذخیره‌سازی اتمی
    """

    def __init__(self, news_file: str = NEWS_FILE):
        self.path = Path(news_file)
        self._news: list[dict] = []
        self._uid_set: set[str] = set()
        self._load()

    # ── بارگذاری ──────────────────────────────────────────────

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            logger.info("📂 فایل news.json وجود ندارد — از صفر شروع می‌شود")
            self._news = []
            self._uid_set = set()
            return

        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            # پشتیبانی از فرمت‌های مختلف
            if isinstance(data, list):
                self._news = data
            elif isinstance(data, dict):
                self._news = data.get("news", [])
            else:
                self._news = []

            self._uid_set = {
                item.get("uid", "") for item in self._news if item.get("uid")
            }
            logger.info(
                "📂 %d خبر بارگذاری شد از %s", len(self._news), self.path
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("❌ خطا در بارگذاری news.json: %s — از صفر شروع", exc)
            self._news = []
            self._uid_set = set()

    # ── خواندن ────────────────────────────────────────────────

    @property
    def known_uids(self) -> set[str]:
        return self._uid_set.copy()

    def count(self) -> int:
        return len(self._news)

    # ── اضافه کردن ────────────────────────────────────────────

    def add_items(self, items: list[NewsItem]) -> int:
        """
        اخبار جدید را اضافه می‌کند.
        خروجی: تعداد اخبار واقعاً اضافه‌شده
        """
        added = 0
        for item in items:
            if item.uid not in self._uid_set:
                self._news.insert(0, item.to_dict())  # جدیدترین اول
                self._uid_set.add(item.uid)
                added += 1

        # حفظ حداکثر MAX_STORED_NEWS خبر
        if len(self._news) > MAX_STORED_NEWS:
            removed = len(self._news) - MAX_STORED_NEWS
            self._news = self._news[:MAX_STORED_NEWS]
            logger.info("🗑 %d خبر قدیمی حذف شد", removed)

        logger.info("➕ %d خبر جدید اضافه شد (کل: %d)", added, len(self._news))
        return added

    def update_send_status(
        self, uid: str, telegram_ok: bool, bale_ok: bool
    ) -> None:
        """وضعیت ارسال را برای یک خبر به‌روز می‌کند"""
        for item in self._news:
            if item.get("uid") == uid:
                item["sent_telegram"] = telegram_ok
                item["sent_bale"] = bale_ok
                break

    # ── ذخیره‌سازی ────────────────────────────────────────────

    def save(self) -> None:
        """ذخیره اتمی (نوشتن به فایل موقت سپس rename)"""
        try:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "total_count": len(self._news),
                "news": self._news,
            }
            temp_path = self.path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self.path)
            logger.info("💾 news.json ذخیره شد (%d خبر)", len(self._news))
        except OSError as exc:
            logger.error("❌ خطا در ذخیره news.json: %s", exc)
            raise


# ═══════════════════════════════════════════════════════════════
# ۳) آمار اجرا
# ═══════════════════════════════════════════════════════════════
@dataclass
class RunStats:
    run_id: str
    started_at: str
    finished_at: str = ""
    feeds_fetched: int = 0
    raw_collected: int = 0
    after_filter: int  = 0
    new_items: int     = 0
    critical_count: int = 0
    ai_analyzed: int   = 0
    ai_summarized: int = 0
    sent_telegram: int = 0
    sent_bale: int     = 0
    errors: list[str]  = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class RunStatsManager:
    """ذخیره آمار ۴۸ اجرای اخیر در run_stats.json"""

    MAX_RUNS = 48  # ۴۸ ساعت (هر ساعت یک اجرا)

    def __init__(self, stats_file: str = RUN_STATS_FILE):
        self.path = Path(stats_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_run(self, stats: RunStats) -> None:
        """آمار یک اجرا را ذخیره می‌کند"""
        try:
            existing = self._load_all()
            existing.insert(0, stats.to_dict())
            existing = existing[: self.MAX_RUNS]

            payload = {
                "last_run": stats.started_at,
                "total_runs_stored": len(existing),
                "runs": existing,
            }
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("📊 آمار اجرا ذخیره شد")
        except Exception as exc:
            logger.error("❌ خطا در ذخیره run_stats: %s", exc)

    def _load_all(self) -> list[dict]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data.get("runs", [])
        except Exception:
            pass
        return []
