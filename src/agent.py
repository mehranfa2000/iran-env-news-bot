# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/agent.py  ·  v4.1  ·  ساختار داده، ذخیره‌سازی و آمار اجرا            ║
# ║  NewsItem dataclass · StorageManager · RunStats                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import (
    NEWS_FILE,
    RUN_STATS_FILE,
    MAX_STORED_NEWS,
    MAX_RUN_STATS,
    DEFAULT_CATEGORY,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. NewsItem — ساختار داده یک خبر
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NewsItem:
    """
    ساختار کامل یک خبر محیط‌زیستی پردازش‌شده.
    این همان ساختاری است که در data/news.json ذخیره می‌شود.
    """

    # ── فیلدهای پایه (از RawArticle) ────────────────────────────────────────
    uid:          str                    # sha256(link)[:16] — یکتا
    title:        str                    # عنوان خبر
    link:         str                    # لینک کامل خبر
    summary:      str                    # خلاصه خبر (حداکثر ۵۰۰ کاراکتر)
    source:       str                    # نام منبع (مثل «مهر — محیط‌زیست»)
    image_url:    Optional[str]          # لینک تصویر (یا None)
    dedicated:    bool                   # آیا فید اختصاصی محیط‌زیست است؟
    tags:         list[str]              # تگ‌های فید

    # ── فیلدهای فیلتر ───────────────────────────────────────────────────────
    score:        int                    # امتیاز کلیدواژه
    category:     str                    # دسته‌بندی (مثل «wildlife»)
    critical:     bool                   # آیا بحرانی است؟ (score ≥ 15)

    # ── فیلدهای زمانی ───────────────────────────────────────────────────────
    published_at: str                    # زمان دریافت ISO 8601 (UTC)
    shamsi_date:  str                    # تاریخ شمسی (مثل «۱۴۰۵/۰۸/۳۳ ۲۱:۳۰»)

    # ── فیلدهای AI ──────────────────────────────────────────────────────────
    ai_summary:   Optional[str]          # خلاصه AI (برای خبرهای عادی)
    pr_analysis:  Optional[dict]         # تحلیل کامل ۹ فیلد (برای بحرانی)

    # ── وضعیت ارسال ─────────────────────────────────────────────────────────
    sent:         bool = False           # آیا به کانال‌ها ارسال شده؟

    # ══════════════════════════════════════════════════════════════════════════
    #  متدهای کمکی
    # ══════════════════════════════════════════════════════════════════════════

    def to_dict(self) -> dict:
        """تبدیل به dict برای ذخیره JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        """ساخت NewsItem از dict خوانده‌شده از JSON."""
        return cls(
            uid          = data.get("uid", ""),
            title        = data.get("title", ""),
            link         = data.get("link", ""),
            summary      = data.get("summary", ""),
            source       = data.get("source", ""),
            image_url    = data.get("image_url"),
            dedicated    = data.get("dedicated", True),
            tags         = data.get("tags", []),
            score        = data.get("score", 0),
            category     = data.get("category", DEFAULT_CATEGORY),
            critical     = data.get("critical", False),
            published_at = data.get("published_at", ""),
            shamsi_date  = data.get("shamsi_date", ""),
            ai_summary   = data.get("ai_summary"),
            pr_analysis  = data.get("pr_analysis"),
            sent         = data.get("sent", False),
        )

    @property
    def category_emoji(self) -> str:
        """ایموجی دسته‌بندی."""
        from src.config import CATEGORIES
        return CATEGORIES.get(self.category, {}).get("emoji", "🌿")

    @property
    def category_label(self) -> str:
        """برچسب فارسی دسته‌بندی."""
        from src.config import CATEGORIES
        return CATEGORIES.get(self.category, {}).get("label", self.category)


# ══════════════════════════════════════════════════════════════════════════════
#  ۲. StorageManager — مدیریت news.json
# ══════════════════════════════════════════════════════════════════════════════

class StorageManager:
    """
    مدیریت ذخیره‌سازی اخبار در data/news.json.

    عملیات:
    · load()   → بارگذاری از فایل
    · save()   → ذخیره به فایل (مرتب‌شده بر اساس زمان)
    · add()    → اضافه کردن خبر جدید
    · update() → بروزرسانی خبر موجود
    · exists() → بررسی تکراری بودن
    · get()    → دریافت خبر با uid
    """

    def __init__(self) -> None:
        self._items: dict[str, NewsItem] = {}   # uid → NewsItem

    # ──────────────────────────────────────────────────────────────────────────
    @property
    def items(self) -> list[NewsItem]:
        """لیست همه اخبار (مرتب بر اساس زمان — جدیدترین اول)."""
        return sorted(
            self._items.values(),
            key=lambda x: x.published_at,
            reverse=True,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def load(self) -> None:
        """بارگذاری اخبار از data/news.json."""
        if not NEWS_FILE.exists():
            logger.info("📂 news.json وجود ندارد — شروع خالی")
            self._items = {}
            return

        try:
            raw_text = NEWS_FILE.read_text(encoding="utf-8").strip()

            if not raw_text:
                logger.warning("⚠️ news.json خالی است")
                self._items = {}
                return

            data = json.loads(raw_text)

            if not isinstance(data, list):
                logger.warning("⚠️ news.json فرمت نامعتبر دارد — شروع خالی")
                self._items = {}
                return

            loaded = 0
            for item_dict in data:
                try:
                    item = NewsItem.from_dict(item_dict)
                    if item.uid:
                        self._items[item.uid] = item
                        loaded += 1
                except Exception as exc:
                    logger.debug("⚠️ خطا در بارگذاری یک خبر: %s", exc)

            logger.info("📥 %d خبر بارگذاری شد", loaded)

        except json.JSONDecodeError as exc:
            logger.error("❌ خطای JSON در news.json: %s", exc)
            self._items = {}
        except Exception as exc:
            logger.error("❌ خطا در بارگذاری news.json: %s", exc)
            self._items = {}

    # ──────────────────────────────────────────────────────────────────────────
    def save(self) -> None:
        """
        ذخیره اخبار در data/news.json.
        · مرتب‌سازی: جدیدترین اول
        · حداکثر MAX_STORED_NEWS خبر نگه می‌دارد
        · فرمت JSON فارسی-پسند (ensure_ascii=False)
        """
        try:
            # مرتب‌سازی و برش
            sorted_items = sorted(
                self._items.values(),
                key=lambda x: x.published_at,
                reverse=True,
            )[:MAX_STORED_NEWS]

            data = [item.to_dict() for item in sorted_items]

            # اطمینان از وجود پوشه
            NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)

            NEWS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("💾 %d خبر ذخیره شد در news.json", len(data))

        except Exception as exc:
            logger.error("❌ خطا در ذخیره news.json: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    def add(self, item: NewsItem) -> bool:
        """
        اضافه کردن خبر جدید.
        اگر uid قبلاً وجود داشت → False (تکراری)
        در غیر این صورت → True
        """
        if item.uid in self._items:
            return False
        self._items[item.uid] = item
        return True

    # ──────────────────────────────────────────────────────────────────────────
    def update(self, item: NewsItem) -> None:
        """بروزرسانی خبر موجود (مثلاً بعد از تحلیل AI یا ارسال)."""
        self._items[item.uid] = item

    # ──────────────────────────────────────────────────────────────────────────
    def exists(self, uid: str) -> bool:
        """بررسی می‌کند آیا خبر با این uid قبلاً ذخیره شده."""
        return uid in self._items

    # ──────────────────────────────────────────────────────────────────────────
    def get(self, uid: str) -> Optional[NewsItem]:
        """دریافت خبر با uid — اگر نبود None."""
        return self._items.get(uid)

    # ──────────────────────────────────────────────────────────────────────────
    def count(self) -> int:
        """تعداد کل اخبار ذخیره‌شده."""
        return len(self._items)

    # ──────────────────────────────────────────────────────────────────────────
    def count_today(self) -> int:
        """تعداد اخبار امروز (UTC)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return sum(
            1 for item in self._items.values()
            if item.published_at.startswith(today)
        )

    # ──────────────────────────────────────────────────────────────────────────
    def count_ai_today(self) -> int:
        """تعداد اخباری که امروز AI آن‌ها را تحلیل کرده."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return sum(
            1 for item in self._items.values()
            if item.published_at.startswith(today)
            and (item.ai_summary or item.pr_analysis)
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ۳. RunStats — آمار هر اجرا
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RunStats:
    """
    آمار یک اجرای کامل سیستم.
    در data/run_stats.json ذخیره می‌شود (حداکثر ۴۸ رکورد).
    """
    run_id:            str
    start_time:        str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time:          str = ""
    duration_seconds:  float = 0.0

    # آمار مراحل
    total_collected:   int = 0    # جمع‌آوری
    new_articles:      int = 0    # خبرهای جدید (غیر تکراری)
    filtered_articles: int = 0    # خبرهای تأیید شده توسط فیلتر
    ai_analyzed:       int = 0    # تحلیل کامل AI
    ai_summarized:     int = 0    # خلاصه AI
    sent_count:        int = 0    # ارسال موفق
    failed_count:      int = 0    # ارسال ناموفق

    # وضعیت کلی
    success:           bool = True
    error_message:     str  = ""

    # ──────────────────────────────────────────────────────────────────────────
    def finish(self, success: bool = True, error: str = "") -> None:
        """ثبت زمان پایان و محاسبه مدت اجرا."""
        end = datetime.now(timezone.utc)
        self.end_time         = end.isoformat()
        self.success          = success
        self.error_message    = error

        try:
            start = datetime.fromisoformat(self.start_time)
            self.duration_seconds = round((end - start).total_seconds(), 2)
        except Exception:
            self.duration_seconds = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """تبدیل به dict برای ذخیره JSON."""
        return {
            "run_id":            self.run_id,
            "start_time":        self.start_time,
            "end_time":          self.end_time,
            "duration_seconds":  self.duration_seconds,
            "total_collected":   self.total_collected,
            "new_articles":      self.new_articles,
            "filtered_articles": self.filtered_articles,
            "ai_analyzed":       self.ai_analyzed,
            "ai_summarized":     self.ai_summarized,
            "sent_count":        self.sent_count,
            "failed_count":      self.failed_count,
            "success":           self.success,
            "error_message":     self.error_message,
        }

    # ──────────────────────────────────────────────────────────────────────────
    def save(self) -> None:
        """
        ذخیره آمار این اجرا در data/run_stats.json.
        آمارهای قبلی حفظ می‌شوند (حداکثر MAX_RUN_STATS رکورد).
        """
        try:
            # بارگذاری آمارهای قبلی
            existing: list[dict] = []
            if RUN_STATS_FILE.exists():
                try:
                    raw = RUN_STATS_FILE.read_text(encoding="utf-8").strip()
                    if raw:
                        existing = json.loads(raw)
                        if not isinstance(existing, list):
                            existing = []
                except Exception:
                    existing = []

            # اضافه کردن آمار جدید
            existing.insert(0, self.to_dict())

            # حفظ حداکثر MAX_RUN_STATS رکورد
            existing = existing[:MAX_RUN_STATS]

            # ذخیره
            RUN_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            RUN_STATS_FILE.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "📊 آمار اجرا ذخیره شد — مدت: %.1fs | ارسال: %d",
                self.duration_seconds,
                self.sent_count,
            )

        except Exception as exc:
            logger.error("❌ خطا در ذخیره run_stats.json: %s", exc)
