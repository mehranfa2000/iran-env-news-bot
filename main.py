#!/usr/bin/env python3
"""
main.py — نقطه ورود سامانه پایش هوشمند محیط‌زیست
نسخه: 4.2.0

تغییرات v4.2:
- published_at از زمان واقعی RSS (نه datetime.now)
- run_stats.json کامل با تمام فیلدهای داشبورد
- StorageManager با enforce سقف و uid_set برای جستجوی O(1)
- Logging به فایل با rotation
- خروج با کد مناسب برای GitHub Actions
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jdatetime

# ─── import داخلی ─────────────────────────────────────────────────────────────
# توجه: اگر src/ وجود دارد، این‌ها را به src.X تغییر بده
from src.collector import collect_all, RawArticle
from src.filter import filter_articles
from src.analyzer import analyze_items, load_ai_usage
from src.sender import send_items
from src.config import (
    NEWS_JSON_PATH,
    STATS_JSON_PATH,
    LOG_PATH,
    MAX_NEWS_PER_RUN,
    MAX_STORED_NEWS,
)

# ─── Logging ──────────────────────────────────────────────────────────────────
def _setup_logging() -> None:
    """
    Logging چندلایه:
    - Console: INFO+
    - File (data/agent.log): INFO+ با rotation 5MB×3
    """
    Path("data").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # جلوگیری از duplicate handler در اجراهای تکراری
    if root.handlers:
        root.handlers.clear()

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    root.addHandler(ch)

    # File با rotation
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_PATH,
            maxBytes=5 * 1024 * 1024,   # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG)       # فایل: DEBUG هم ثبت شود
        root.addHandler(fh)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"فایل لاگ ایجاد نشد: {exc}")


log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# مدل داده NewsItem
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    """
    خبر پردازش‌شده — واحد اصلی ذخیره‌سازی.

    فیلدهای کلیدی:
    - uid:          sha256(link)[:16] — شناسه یکتا
    - published_at: زمان واقعی خبر از RSS (ISO 8601 با timezone)
    - shamsi_date:  تبدیل شده از published_at (نه datetime.now)
    - pr_analysis:  نتیجه تحلیل AI برای اخبار بحرانی (dict ۹ فیلدی)
    - ai_summary:   خلاصه AI برای اخبار معمولی
    """
    # ─── فیلدهای اجباری ───
    uid:          str
    title:        str
    link:         str
    source:       str
    category:     str
    score:        int
    published_at: str           # ISO 8601، زمان واقعی خبر
    shamsi_date:  str           # مثال: ۱۴۰۳/۰۹/۱۵ ۱۴:۳۰

    # ─── فیلدهای اختیاری ───
    summary:      str            = ""
    image_url:    Optional[str]  = None
    dedicated:    bool           = True
    tags:         list[str]      = field(default_factory=list)
    critical:     bool           = False
    ai_summary:   Optional[str]  = None
    pr_analysis:  Optional[dict] = None
    sent:         bool           = False

    @staticmethod
    def make_uid(link: str) -> str:
        return hashlib.sha256(link.strip().encode("utf-8")).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════
# StorageManager
# ══════════════════════════════════════════════════════════════════════════════
class StorageManager:
    """
    مدیریت news.json.

    ویژگی‌ها:
    - جستجوی uid در O(1) با uid_set
    - Enforce سقف MAX_STORED_NEWS (قدیمی‌ترین حذف)
    - بارگذاری با مقاومت در برابر فیلدهای ناشناخته (forward compat)
    """

    def __init__(self, path: str = NEWS_JSON_PATH) -> None:
        self._path    = Path(path)
        self._items:  list[NewsItem] = []
        self._uid_set: set[str]      = set()
        self._load()

    # ── بارگذاری ──────────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if not self._path.exists() or self._path.stat().st_size == 0:
                log.info("news.json خالی یا وجود ندارد — شروع تازه")
                return

            raw: list[dict] = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                log.error("news.json فرمت لیست ندارد — شروع تازه")
                return

            loaded = skipped = 0
            for item_dict in raw:
                try:
                    # فیلدهای ناشناخته را نادیده بگیر (forward compat)
                    known = {
                        k: v for k, v in item_dict.items()
                        if k in NewsItem.__dataclass_fields__
                    }
                    item = NewsItem(**known)   # type: ignore[arg-type]
                    if item.uid not in self._uid_set:
                        self._items.append(item)
                        self._uid_set.add(item.uid)
                        loaded += 1
                    else:
                        skipped += 1
                except Exception as e:
                    log.debug(f"آیتم نادیده گرفته شد: {e}")
                    skipped += 1

            log.info(f"📂 StorageManager: {loaded} خبر لود شد، {skipped} رد شد")

        except json.JSONDecodeError as e:
            log.error(f"❌ news.json خراب است: {e} — شروع تازه")
        except Exception as e:
            log.error(f"❌ خطای بارگذاری: {e}")

    # ── API عمومی ─────────────────────────────────────────────────────────────
    @property
    def existing_uids(self) -> set[str]:
        return self._uid_set

    def add(self, item: NewsItem) -> bool:
        """
        اضافه کردن خبر جدید.
        Returns True اگر اضافه شد، False اگر تکراری بود.
        """
        if item.uid in self._uid_set:
            return False
        self._items.append(item)
        self._uid_set.add(item.uid)
        return True

    def update_item(self, item: NewsItem) -> None:
        """بروزرسانی آیتم موجود (مثلاً بعد از تحلیل AI یا ارسال)."""
        for i, existing in enumerate(self._items):
            if existing.uid == item.uid:
                self._items[i] = item
                return

    def get_all(self) -> list[NewsItem]:
        return list(self._items)

    def get_unsent(self) -> list[NewsItem]:
        return [i for i in self._items if not i.sent]

    # ── ذخیره ──────────────────────────────────────────────────────────────────
    def save(self) -> bool:
        """
        ذخیره با enforce سقف MAX_STORED_NEWS.
        قدیمی‌ترین آیتم‌ها (کمترین index) حذف می‌شوند.
        """
        # enforce سقف
        if len(self._items) > MAX_STORED_NEWS:
            removed = len(self._items) - MAX_STORED_NEWS
            self._items   = self._items[-MAX_STORED_NEWS:]
            self._uid_set = {i.uid for i in self._items}
            log.info(f"🗑  {removed} خبر قدیمی حذف شد (سقف: {MAX_STORED_NEWS})")

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    [asdict(item) for item in self._items],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info(f"💾 news.json ذخیره شد ({len(self._items)} خبر)")
            return True
        except Exception as e:
            log.error(f"❌ خطا در ذخیره news.json: {e}")
            return False


# ══════════════════════════════════════════════════════════════════════════════
# تبدیل RawArticle → NewsItem
# ══════════════════════════════════════════════════════════════════════════════
def _raw_to_newsitem(
    raw: RawArticle,
    score: int,
    category: str,
    critical: bool,
) -> NewsItem:
    """
    تبدیل خبر خام به NewsItem.

    published_at: از زمان واقعی RSS (نه datetime.now).
    shamsi_date:  محاسبه‌شده از published_at واقعی.
    """
    # ── زمان واقعی خبر ────────────────────────────────────────────────────────
    pub_dt: datetime
    try:
        pub_dt = datetime.fromisoformat(raw.published_at)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
    except Exception:
        # fallback به زمان فعلی فقط اگر RSS زمان نداشت
        pub_dt = datetime.now(timezone.utc)
        log.debug(f"زمان RSS ناقص برای '{raw.title[:40]}' — از زمان فعلی استفاده شد")

    # ── تبدیل به شمسی ─────────────────────────────────────────────────────────
    try:
        shamsi = jdatetime.datetime.fromgregorian(
            datetime=pub_dt
        ).strftime("%Y/%m/%d %H:%M")
    except Exception:
        shamsi = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
        log.debug(f"تبدیل شمسی ناموفق برای '{raw.title[:40]}'")

    return NewsItem(
        uid=raw.uid,
        title=raw.title,
        link=raw.link,
        source=raw.source,
        category=category,
        score=score,
        published_at=pub_dt.isoformat(),
        shamsi_date=shamsi,
        summary=raw.summary,
        image_url=raw.image_url,
        dedicated=raw.dedicated,
        tags=raw.tags,
        critical=critical,
        ai_summary=None,
        pr_analysis=None,
        sent=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# run_stats.json
# ══════════════════════════════════════════════════════════════════════════════
def _save_run_stats(
    *,
    collected: int,
    filtered:  int,
    added:     int,
    sent:      int,
    failed:    int,
    ai_critical: int,
    ai_summary:  int,
    all_news:  list[NewsItem],
    duration_sec: float,
) -> None:
    """
    آمار کامل ران را در run_stats.json ذخیره می‌کند.

    فیلدهای خوانده‌شده توسط داشبورد:
    - last_run_shamsi, last_run_collected, last_run_filtered,
      last_run_sent, last_run_failed, last_run_duration_sec
    - total_news_stored, total_sent, total_critical
    - category_counts, source_counts
    - ai_date, ai_used_today  (← برای analyzer حفظ می‌شود)
    - system_version, status
    """
    now_utc    = datetime.now(timezone.utc)
    shamsi_now = jdatetime.datetime.fromgregorian(
        datetime=now_utc
    ).strftime("%Y/%m/%d %H:%M")

    # آمار از کل اخبار ذخیره‌شده
    cat_counts  = dict(Counter(n.category       for n in all_news).most_common())
    src_counts  = dict(Counter(n.source         for n in all_news).most_common(10))
    total_crit  = sum(1 for n in all_news if n.critical)
    total_sent  = sum(1 for n in all_news if n.sent)

    # ai_date و ai_used_today را از فایل موجود حفظ کن (تا analyzer بخواند)
    path = Path(STATS_JSON_PATH)
    existing: dict = {}
    try:
        if path.exists() and path.stat().st_size > 0:
            existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass

    ai_used_today = load_ai_usage()   # مستقیم از analyzer می‌خواند

    stats: dict = {
        # ── آخرین ران ──────────────────────────────────────
        "last_run":              now_utc.isoformat(),
        "last_run_shamsi":       shamsi_now,
        "last_run_collected":    collected,
        "last_run_filtered":     filtered,
        "last_run_added":        added,
        "last_run_sent":         sent,
        "last_run_failed":       failed,
        "last_run_ai_critical":  ai_critical,
        "last_run_ai_summary":   ai_summary,
        "last_run_duration_sec": round(duration_sec, 1),

        # ── کلی ────────────────────────────────────────────
        "total_news_stored": len(all_news),
        "total_sent":        total_sent,
        "total_critical":    total_crit,

        # ── توزیع ──────────────────────────────────────────
        "category_counts": cat_counts,
        "source_counts":   src_counts,

        # ── AI (حفظ شده بین ران‌ها) ────────────────────────
        "ai_date":        existing.get("ai_date", now_utc.strftime("%Y-%m-%d")),
        "ai_used_today":  ai_used_today,

        # ── سیستم ──────────────────────────────────────────
        "system_version": "4.2",
        "status":         "ok",
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"📊 run_stats.json ذخیره شد — {shamsi_now}")
    except Exception as e:
        log.error(f"❌ خطا در ذخیره run_stats.json: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# تابع اصلی
# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    """
    Returns:
        0 — موفق
        1 — خطای غیرقابل بازیابی
    """
    t0 = time.monotonic()
    _setup_logging()

    shamsi_now = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    log.info("=" * 65)
    log.info("🌿 سامانه پایش هوشمند محیط‌زیست — نسخه 4.2")
    log.info(f"⏰ شروع: {shamsi_now}")
    log.info("=" * 65)

    exit_code = 0

    try:
        # ── ۱. بارگذاری ─────────────────────────────────────────────────────
        storage      = StorageManager()
        existing_uid = storage.existing_uids

        # ── ۲. جمع‌آوری ─────────────────────────────────────────────────────
        log.info("▶ مرحله ۱/۵: جمع‌آوری RSS")
        raw_articles = collect_all()
        collected    = len(raw_articles)
        log.info(f"   {collected} خبر خام جمع‌آوری شد")

        # ── ۳. فیلتر ────────────────────────────────────────────────────────
        log.info("▶ مرحله ۲/۵: فیلتر ۴ لایه‌ای")
        filtered_pairs = filter_articles(raw_articles, existing_uid)
        filtered       = len(filtered_pairs)
        log.info(f"   {filtered} خبر از {collected} قبول شد")

        # ── ۴. تبدیل + ذخیره‌سازی ───────────────────────────────────────────
        log.info("▶ مرحله ۳/۵: تبدیل و ذخیره")
        new_items: list[NewsItem] = []

        for raw, f_result in filtered_pairs[:MAX_NEWS_PER_RUN]:
            item = _raw_to_newsitem(
                raw,
                score=f_result.score,
                category=f_result.category,
                critical=f_result.critical,
            )
            if storage.add(item):
                new_items.append(item)

        added = len(new_items)
        log.info(f"   {added} خبر جدید اضافه شد")

        # ── ۵. تحلیل AI ─────────────────────────────────────────────────────
        log.info("▶ مرحله ۴/۵: تحلیل AI")
        ai_critical = ai_sum = 0
        if new_items:
            new_items, ai_critical, ai_sum = analyze_items(new_items)
            # بروزرسانی storage با ai_summary / pr_analysis
            for item in new_items:
                storage.update_item(item)
            log.info(f"   AI: بحرانی={ai_critical} | خلاصه={ai_sum}")
        else:
            log.info("   خبر جدیدی برای تحلیل نیست")

        # ── ۶. ارسال ────────────────────────────────────────────────────────
        log.info("▶ مرحله ۵/۵: ارسال به تلگرام و بله")
        sent = failed = 0
        if new_items:
            sent, failed = send_items(new_items)
            # بروزرسانی وضعیت sent در storage
            for item in new_items:
                storage.update_item(item)
            log.info(f"   ارسال: موفق={sent} | ناموفق={failed}")
        else:
            log.info("   خبری برای ارسال وجود ندارد")

        # ── ۷. ذخیره نهایی ──────────────────────────────────────────────────
        storage.save()

    except KeyboardInterrupt:
        log.warning("⚠️  توقف توسط کاربر (KeyboardInterrupt)")
        exit_code = 1
    except Exception as exc:
        log.exception(f"❌ خطای غیرمنتظره: {exc}")
        exit_code = 1
        collected = filtered = added = sent = failed = ai_critical = ai_sum = 0
        storage   = StorageManager()   # خواندن مجدد از دیسک برای آمار

    finally:
        # ── ۸. ثبت آمار (همیشه اجرا می‌شود) ───────────────────────────────
        duration = time.monotonic() - t0
        try:
            _save_run_stats(
                collected=collected,
                filtered=filtered,
                added=added,
                sent=sent,
                failed=failed,
                ai_critical=ai_critical,
                ai_summary=ai_sum,
                all_news=storage.get_all(),
                duration_sec=duration,
            )
        except Exception as e:
            log.error(f"خطا در ذخیره run_stats: {e}")

        log.info("=" * 65)
        log.info(
            f"{'✅' if exit_code == 0 else '❌'} "
            f"ران تمام شد — {duration:.1f}s"
        )
        log.info(
            f"   📡 جمع:{collected} | 🔍 فیلتر:{filtered} | "
            f"💾 جدید:{added} | 📨 ارسال:{sent} | ❌ ناموفق:{failed}"
        )
        log.info(f"   🤖 AI بحرانی:{ai_critical} | AI خلاصه:{ai_sum}")
        log.info("=" * 65)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
