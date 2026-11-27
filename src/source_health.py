"""
source_health.py — سلامت منابع RSS (مرحله ۲ / آیتم ۴)
نسخه: 4.6.0

برای هر فید ثبت می‌کند: خطاهای پیاپی، آخرین موفقیت/شکست، علت خطا،
میانگین تأخیر (EMA)، تعداد آخرین دریافت.

سیاست غیرفعال‌سازی خودکار:
- بعد از SOURCE_FAIL_THRESHOLD ران پیاپی ناموفق، فید برای مدتی کنار گذاشته می‌شود
  (جلوگیری از اتلاف زمان/retry روی فید مرده و لاگ شلوغ)
- مدت کنار گذاشتن نمایی است: ۶ → ۱۲ → ۲۴ → ... تا سقف ۷۲ ساعت
- بعد از پایان مدت، فید «کاوش» می‌شود (یک ران)؛ موفق = فعال، ناموفق = دوبرابر مدت
- هرگز همهٔ فیدها را یک‌جا غیرفعال نمی‌کند (مشکل احتمالاً از شبکهٔ ماست)

رویداد (HealthEvent) فقط روی «تغییر وضعیت» تولید می‌شود: disabled / recovered
→ برای هشدار ادمین بدون اسپم.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from src.config import (
    SOURCE_COOLDOWN_HOURS,
    SOURCE_FAIL_THRESHOLD,
    SOURCE_HEALTH_PATH,
    SOURCE_MAX_COOLDOWN_HOURS,
)
from src.storage import atomic_write_json

log = logging.getLogger(__name__)

_EMA_ALPHA = 0.3


@dataclass(frozen=True)
class HealthEvent:
    kind: str      # "disabled" | "recovered"
    feed: str
    detail: str


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _blank() -> dict[str, Any]:
    return {
        "consecutive_failures": 0,
        "total_runs": 0,
        "total_failures": 0,
        "last_success": None,
        "last_failure": None,
        "last_error": "",
        "last_count": 0,
        "avg_latency_ms": 0.0,
        "disabled_since": None,
        "disabled_until": None,
        "disabled_count": 0,
    }


class SourceHealth:
    def __init__(
        self,
        path: str | Path = SOURCE_HEALTH_PATH,
        *,
        fail_threshold: int = SOURCE_FAIL_THRESHOLD,
        cooldown_hours: float = SOURCE_COOLDOWN_HOURS,
        max_cooldown_hours: float = SOURCE_MAX_COOLDOWN_HOURS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._threshold = max(1, int(fail_threshold))
        self._cooldown = max(0.1, float(cooldown_hours))
        self._max_cooldown = max(self._cooldown, float(max_cooldown_hours))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state: dict[str, dict[str, Any]] = {}
        self._load()

    # ── ذخیره/بارگذاری ───────────────────────────────────────────────────────
    def _load(self) -> None:
        """دادهٔ سلامت حیاتی نیست: خرابی آن اجرا را متوقف نمی‌کند."""
        try:
            if not self._path.exists() or self._path.stat().st_size == 0:
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("ریشه dict نیست")
            for name, st in raw.items():
                if isinstance(st, dict):
                    self._state[str(name)] = {**_blank(), **st}
        except Exception as exc:  # noqa: BLE001
            log.warning("⚠️ source_health.json خوانده نشد (%s) — از صفر شروع می‌شود", exc)
            self._state = {}

    def save(self) -> bool:
        try:
            atomic_write_json(self._path, self._state)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("❌ خطا در ذخیره source_health.json: %s", exc)
            return False

    # ── وضعیت ────────────────────────────────────────────────────────────────
    def get(self, name: str) -> dict[str, Any]:
        return dict(self._state.get(name) or _blank())

    def is_disabled(self, name: str) -> bool:
        until = _parse_dt((self._state.get(name) or {}).get("disabled_until"))
        return until is not None and until > self._clock()

    def filter_active(self, feeds: Sequence[Any]) -> tuple[list[Any], list[tuple[Any, str]]]:
        """(فیدهای فعال، [(فید کنار‌گذاشته‌شده، دلیل)]). هرگز همه را کنار نمی‌گذارد."""
        active, skipped = [], []
        for f in feeds:
            if self.is_disabled(f.name):
                until = self._state[f.name]["disabled_until"]
                skipped.append((f, f"غیرفعال تا {until[:16]}Z — {self._state[f.name]['last_error']}"))
            else:
                active.append(f)
        if feeds and not active:
            log.warning("⚠️ همهٔ فیدها غیرفعال بودند — برای کاوش همه فعال می‌شوند")
            return list(feeds), []
        if skipped:
            log.info("⏸ %d فید در دورهٔ استراحت: %s", len(skipped), ", ".join(f.name for f, _ in skipped))
        return active, skipped

    # ── ثبت نتیجه ────────────────────────────────────────────────────────────
    def record(
        self,
        results: Iterable[Any],
        universe: Sequence[str] | None = None,
    ) -> list[HealthEvent]:
        """
        results: [FeedResult(name, ok, count, latency_ms, error)]
        universe: نام همهٔ فیدهای پیکربندی‌شده (برای «آخرین فعال را نبند» و پاک‌سازی فیدهای حذف‌شده)
        """
        now = self._clock()
        events: list[HealthEvent] = []

        for r in results:
            st = self._state.setdefault(r.name, _blank())
            st["total_runs"] += 1
            if r.latency_ms:
                prev = st["avg_latency_ms"]
                st["avg_latency_ms"] = round(
                    r.latency_ms if not prev else _EMA_ALPHA * r.latency_ms + (1 - _EMA_ALPHA) * prev, 1
                )

            if r.ok:
                was_disabled = st["disabled_since"] is not None
                st.update(
                    consecutive_failures=0, last_success=now.isoformat(), last_count=r.count,
                    last_error="", disabled_until=None, disabled_since=None, disabled_count=0,
                )
                if was_disabled:
                    events.append(HealthEvent("recovered", r.name, f"{r.count} خبر"))
                continue

            st["total_failures"] += 1
            st["consecutive_failures"] += 1
            st["last_failure"] = now.isoformat()
            st["last_error"] = r.error or "نامشخص"
            st["last_count"] = 0

            if st["consecutive_failures"] < self._threshold:
                continue
            if universe is not None and not any(
                n != r.name and not self.is_disabled(n) for n in universe
            ):
                log.warning("[%s] آخرین فید فعال است؛ غیرفعال نمی‌شود", r.name)
                continue

            st["disabled_count"] += 1
            hours = min(self._cooldown * 2 ** (st["disabled_count"] - 1), self._max_cooldown)
            st["disabled_until"] = (now + timedelta(hours=hours)).isoformat()
            if st["disabled_since"] is None:
                st["disabled_since"] = now.isoformat()
                events.append(HealthEvent(
                    "disabled", r.name,
                    f"{st['consecutive_failures']} خطای پیاپی؛ آخرین خطا: {st['last_error']}؛ "
                    f"استراحت {hours:g} ساعت",
                ))
            log.warning("⏸ [%s] تا %g ساعت غیرفعال شد (%s)", r.name, hours, st["last_error"])

        if universe is not None:
            for gone in set(self._state) - set(universe):
                del self._state[gone]
        return events

    # ── خلاصه (برای run_stats / گزارش) ───────────────────────────────────────
    def summary(self, universe: Sequence[str]) -> dict[str, Any]:
        disabled = [n for n in universe if self.is_disabled(n)]
        return {
            "sources_total": len(universe),
            "sources_active": len(universe) - len(disabled),
            "sources_disabled": disabled,
        }
