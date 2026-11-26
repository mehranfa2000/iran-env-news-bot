"""
storage.py — ذخیره‌سازی اخبار (C1)
نسخه: 4.3.0

ویژگی‌ها:
- NewsItem و StorageManager از main.py اینجا منتقل شده‌اند
- نوشتن اتمیک (tmp + fsync + os.replace) → هیچ‌وقت فایل نیمه‌نوشته نمی‌ماند
- فایل خراب = توقف (StorageCorruptError)، نه شروع تازه؛ وگرنه کل تاریخچه پاک
  و همه خبرها دوباره ارسال می‌شد
- enforce سقف: ۱) حذف خبر قدیمی‌تر از MAX_NEWS_AGE_DAYS  ۲) سقف MAX_STORED_NEWS
- «سنگ‌قبر» (seen_uids.json): uid خبرهای حذف‌شده مدتی نگه داشته می‌شود تا
  خبری که هنوز در RSS هست بعد از پاکسازی دوباره ارسال نشود
- جستجوی O(1) برای add / update_item
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import (
    MAX_NEWS_AGE_DAYS,
    MAX_STORED_NEWS,
    NEWS_JSON_PATH,
    SEEN_UIDS_PATH,
    SEEN_UIDS_RETENTION_DAYS,
)

log = logging.getLogger(__name__)

# سقف سخت تعداد سنگ‌قبرها (حدود ۸۰۰KB) تا فایل بی‌نهایت بزرگ نشود
_SEEN_HARD_CAP = 20_000


class StorageCorruptError(RuntimeError):
    """news.json وجود دارد ولی قابل‌خواندن نیست."""


# ══════════════════════════════════════════════════════════════════════════════
# ابزارهای کمکی
# ══════════════════════════════════════════════════════════════════════════════
def atomic_write_json(path: str | Path, data: Any, *, indent: int | None = 2) -> None:
    """
    نوشتن اتمیک JSON.
    اگر وسط کار پروسه بمیرد، فایل اصلی دست‌نخورده می‌ماند.
    در صورت خطا exception بالا می‌رود (فراخواننده تصمیم می‌گیرد).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # اتمیک روی Linux/macOS/Windows
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _parse_dt(value: Any) -> Optional[datetime]:
    """ISO 8601 → datetime آگاه از timezone (UTC پیش‌فرض). خطا → None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# مدل داده NewsItem
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    """
    خبر پردازش‌شده — واحد اصلی ذخیره‌سازی.

    - uid: sha256(link)[:16]
    - published_at: زمان واقعی خبر (ISO 8601 با timezone)
    - pr_analysis: نتیجه تحلیل AI برای اخبار بحرانی (dict)
    - ai_summary: خلاصه AI برای اخبار معمولی
    """

    # ─── فیلدهای اجباری ───
    uid: str
    title: str
    link: str
    source: str
    category: str
    score: int
    published_at: str
    shamsi_date: str

    # ─── فیلدهای اختیاری ───
    summary: str = ""
    image_url: Optional[str] = None
    dedicated: bool = True
    tags: list[str] = field(default_factory=list)
    critical: bool = False
    ai_summary: Optional[str] = None
    pr_analysis: Optional[dict] = None
    sent: bool = False

    @staticmethod
    def make_uid(link: str) -> str:
        return hashlib.sha256(link.strip().encode("utf-8")).hexdigest()[:16]


_NEWSITEM_FIELDS = {f.name for f in fields(NewsItem)}


# ══════════════════════════════════════════════════════════════════════════════
# StorageManager
# ══════════════════════════════════════════════════════════════════════════════
class StorageManager:
    """
    مدیریت news.json + seen_uids.json.

    استفاده:
        storage = StorageManager()
        if storage.add(item): ...
        storage.update_item(item)
        storage.save()          # prune + نوشتن اتمیک
    """

    def __init__(
        self,
        path: str | Path = NEWS_JSON_PATH,
        *,
        seen_path: str | Path = SEEN_UIDS_PATH,
        max_items: int = MAX_STORED_NEWS,
        max_age_days: int = MAX_NEWS_AGE_DAYS,
        seen_retention_days: int = SEEN_UIDS_RETENTION_DAYS,
        strict: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        strict=True: اگر news.json خراب باشد StorageCorruptError می‌دهد.
        strict=False: فایل خراب به *.corrupt-<زمان> منتقل می‌شود و کار تازه شروع می‌شود.
        clock: فقط برای تست (تزریق زمان).
        """
        self._path = Path(path)
        self._seen_path = Path(seen_path)
        self._max_items = max(1, int(max_items))
        self._max_age_days = max(1, int(max_age_days))
        self._seen_retention_days = max(1, int(seen_retention_days))
        self._strict = strict
        self._clock = clock or (lambda: datetime.now(timezone.utc))

        self._items: dict[str, NewsItem] = {}   # uid → item (ترتیب درج حفظ می‌شود)
        self._seen: dict[str, str] = {}         # uid → published_at (سنگ‌قبر)

        self._load_items()
        self._load_seen()

    # ── بارگذاری ──────────────────────────────────────────────────────────────
    def _load_items(self) -> None:
        path = self._path
        if not path.exists() or path.stat().st_size == 0:
            log.info("news.json خالی یا وجود ندارد — شروع تازه")
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("ریشهٔ JSON لیست نیست")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            self._handle_corrupt(exc)
            return

        loaded = dupes = bad = 0
        for entry in raw:
            try:
                if not isinstance(entry, dict):
                    raise TypeError("آیتم dict نیست")
                known = {k: v for k, v in entry.items() if k in _NEWSITEM_FIELDS}
                item = NewsItem(**known)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                bad += 1
                log.debug("آیتم نامعتبر نادیده گرفته شد: %s", exc)
                continue
            if item.uid in self._items:
                dupes += 1
                continue
            self._items[item.uid] = item
            loaded += 1

        log.info("📂 StorageManager: %d خبر لود شد (تکراری: %d، نامعتبر: %d)", loaded, dupes, bad)
        if bad:
            log.warning("⚠️ %d آیتم نامعتبر در news.json بود و در ذخیرهٔ بعدی حذف می‌شود", bad)

    def _handle_corrupt(self, exc: Exception) -> None:
        if self._strict:
            raise StorageCorruptError(
                f"{self._path} خراب است ({exc}). برای جلوگیری از پاک‌شدن تاریخچه "
                "و ارسال مجدد همهٔ خبرها، اجرا متوقف شد. فایل را از تاریخچهٔ git "
                "بازگردانید یا آن را حذف کنید."
            ) from exc
        stamp = self._clock().strftime("%Y%m%dT%H%M%SZ")
        quarantine = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
        try:
            shutil.copy2(self._path, quarantine)
            log.error("❌ news.json خراب بود → کپی در %s و شروع تازه (%s)", quarantine.name, exc)
        except OSError as copy_exc:
            log.error("❌ news.json خراب بود و قرنطینه هم ممکن نشد: %s / %s", exc, copy_exc)

    def _load_seen(self) -> None:
        """سنگ‌قبرها فقط شبکهٔ ایمنی‌اند؛ خرابی آن‌ها نباید اجرا را متوقف کند."""
        path = self._seen_path
        try:
            if not path.exists() or path.stat().st_size == 0:
                return
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("ریشهٔ JSON dict نیست")
            self._seen = {str(k): str(v) for k, v in raw.items()}
            log.info("📂 seen_uids: %d uid", len(self._seen))
        except Exception as exc:  # noqa: BLE001
            log.warning("⚠️ seen_uids.json خوانده نشد (%s) — خالی شروع می‌شود", exc)
            self._seen = {}

    # ── API عمومی ─────────────────────────────────────────────────────────────
    @property
    def existing_uids(self) -> set[str]:
        """uidهای ذخیره‌شده + سنگ‌قبرها (برای فیلتر ضدتکرار). هر بار کپی تازه."""
        return set(self._items) | set(self._seen)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, uid: object) -> bool:
        return uid in self._items or uid in self._seen

    def get(self, uid: str) -> Optional[NewsItem]:
        return self._items.get(uid)

    def add(self, item: NewsItem) -> bool:
        """True اگر اضافه شد؛ False اگر تکراری بود (ذخیره‌شده یا حذف‌شدهٔ اخیر)."""
        if item.uid in self._items or item.uid in self._seen:
            return False
        self._items[item.uid] = item
        return True

    def update_item(self, item: NewsItem) -> bool:
        """جایگزینی آیتم موجود (O(1)). False اگر uid ناشناخته باشد."""
        if item.uid not in self._items:
            return False
        self._items[item.uid] = item
        return True

    def get_all(self) -> list[NewsItem]:
        return list(self._items.values())

    def get_unsent(self) -> list[NewsItem]:
        return [i for i in self._items.values() if not i.sent]

    def stats(self) -> dict[str, Any]:
        """خلاصهٔ سریع وضعیت ذخیره‌سازی (برای لاگ/healthcheck)."""
        dts = [d for d in (_parse_dt(i.published_at) for i in self._items.values()) if d]
        return {
            "total": len(self._items),
            "unsent": sum(1 for i in self._items.values() if not i.sent),
            "critical": sum(1 for i in self._items.values() if i.critical),
            "seen_uids": len(self._seen),
            "oldest": min(dts).isoformat() if dts else None,
            "newest": max(dts).isoformat() if dts else None,
        }

    # ── پاکسازی ───────────────────────────────────────────────────────────────
    def prune(self) -> dict[str, int]:
        """
        enforce سقف‌ها (در save خودکار صدا زده می‌شود).

        ۱) خبر قدیمی‌تر از max_age_days حذف می‌شود.
        ۲) اگر هنوز بیش از max_items بود، قدیمی‌ترین‌ها (بر اساس published_at) حذف می‌شوند.
        uid هر خبر حذف‌شده به سنگ‌قبر می‌رود. سنگ‌قبرهای منقضی هم پاک می‌شوند.
        """
        now = self._clock()
        cutoff = now - timedelta(days=self._max_age_days)

        # زمان انتشار هر خبر؛ تاریخ نامعتبر = «همین حالا» (هرگز به‌خاطر تاریخ خراب حذف نمی‌شود)
        pub: dict[str, datetime] = {
            uid: _parse_dt(it.published_at) or now for uid, it in self._items.items()
        }

        removed: list[str] = [uid for uid, dt in pub.items() if dt < cutoff]
        aged = len(removed)

        capped = 0
        remaining = len(self._items) - aged
        if remaining > self._max_items:
            gone = set(removed)
            survivors = sorted((uid for uid in pub if uid not in gone), key=lambda u: pub[u])
            extra = survivors[: remaining - self._max_items]
            removed.extend(extra)
            capped = len(extra)

        for uid in removed:
            self._seen[uid] = self._items[uid].published_at or now.isoformat()
            del self._items[uid]

        purged = self._purge_seen(now)

        if removed:
            log.info(
                "🗑 پاکسازی: %d قدیمی‌تر از %d روز، %d بیش از سقف %d",
                aged, self._max_age_days, capped, self._max_items,
            )
        return {"aged": aged, "capped": capped, "seen_purged": purged}

    def _purge_seen(self, now: datetime) -> int:
        cutoff = now - timedelta(days=self._seen_retention_days)
        before = len(self._seen)
        self._seen = {
            uid: ts for uid, ts in self._seen.items()
            if (_parse_dt(ts) or now) >= cutoff
        }
        if len(self._seen) > _SEEN_HARD_CAP:
            newest = sorted(self._seen.items(), key=lambda kv: _parse_dt(kv[1]) or now, reverse=True)
            self._seen = dict(newest[:_SEEN_HARD_CAP])
        return before - len(self._seen)

    # ── ذخیره ─────────────────────────────────────────────────────────────────
    def save(self) -> bool:
        """prune + نوشتن اتمیک هر دو فایل. True فقط اگر هر دو موفق باشند."""
        self.prune()
        ok = True
        try:
            atomic_write_json(self._path, [asdict(i) for i in self._items.values()])
            log.info("💾 news.json ذخیره شد (%d خبر)", len(self._items))
        except Exception as exc:  # noqa: BLE001
            log.error("❌ خطا در ذخیره news.json: %s", exc)
            ok = False
        try:
            # indent=None: فایل فشرده و diff کم‌حجم در git
            atomic_write_json(self._seen_path, self._seen, indent=None)
            log.debug("seen_uids.json ذخیره شد (%d uid)", len(self._seen))
        except Exception as exc:  # noqa: BLE001
            log.error("❌ خطا در ذخیره seen_uids.json: %s", exc)
            ok = False
        return ok
