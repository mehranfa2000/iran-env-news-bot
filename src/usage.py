"""
usage.py — شمارش مصرف و کنترل هزینه/سهمیه (مرحله ۲ / آیتم ۶)
نسخه: 4.7.0

شمارنده‌های روزانه (UTC) در data/usage.json:
  runs, collected, added, duplicates, run_seconds
  ai_requests, ai_errors, ai_prompt_tokens, ai_output_tokens
  tg_ok, tg_fail, bale_ok, bale_fail

- هر تماس واقعی با Gemini شمرده می‌شود، حتی ناموفق (سهمیهٔ API خطاها را هم می‌شمارد؛
  شمارندهٔ ai_used_today در analyzer فقط موفق‌ها را می‌شمارد)
- توکن‌ها از response.usage_metadata خوانده می‌شود (اگر نبود صفر)
- هزینه فقط وقتی تخمین زده می‌شود که قیمت در config تنظیم شده باشد
- هیچ تابعی exception بالا نمی‌دهد؛ شمارش نباید کار اصلی را بشکند
- singleton: tracker() — در main.save() و بقیه ماژول‌ها فقط add()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from src.config import (
    GEMINI_PRICE_IN_PER_M,
    GEMINI_PRICE_OUT_PER_M,
    USAGE_PATH,
    USAGE_RETENTION_DAYS,
)
from src.storage import atomic_write_json

log = logging.getLogger(__name__)

COUNTERS = (
    "runs", "collected", "added", "duplicates", "run_seconds",
    "ai_requests", "ai_errors", "ai_prompt_tokens", "ai_output_tokens",
    "tg_ok", "tg_fail", "bale_ok", "bale_fail",
)


class UsageTracker:
    def __init__(
        self,
        path: str | Path = USAGE_PATH,
        *,
        retention_days: int = USAGE_RETENTION_DAYS,
        price_in: float = GEMINI_PRICE_IN_PER_M,
        price_out: float = GEMINI_PRICE_OUT_PER_M,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._retention = max(1, int(retention_days))
        self._price_in = max(0.0, float(price_in))
        self._price_out = max(0.0, float(price_out))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._days: dict[str, dict[str, float]] = {}
        self._dirty = False
        self._load()

    # ── ذخیره/بارگذاری ───────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_size > 0:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for day, d in raw.items():
                        if isinstance(d, dict):
                            self._days[str(day)] = {k: v for k, v in d.items()
                                                    if isinstance(v, (int, float))}
        except Exception as exc:  # noqa: BLE001
            log.warning("usage.json خوانده نشد (%s) — از صفر", exc)
            self._days = {}

    def save(self) -> bool:
        if not self._dirty:
            return True
        try:
            self._prune()
            atomic_write_json(self._path, self._days)
            self._dirty = False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("usage.json ذخیره نشد: %s", exc)
            return False

    def _prune(self) -> None:
        cutoff = (self._clock() - timedelta(days=self._retention)).strftime("%Y-%m-%d")
        self._days = {d: v for d, v in self._days.items() if d >= cutoff}

    # ── ثبت ──────────────────────────────────────────────────────────────────
    def _today_key(self) -> str:
        return self._clock().strftime("%Y-%m-%d")

    def add(self, **deltas: float) -> None:
        try:
            day = self._days.setdefault(self._today_key(), {})
            for k, v in deltas.items():
                if k in COUNTERS and v:
                    day[k] = round(day.get(k, 0) + v, 3)
                    self._dirty = True
        except Exception as exc:  # noqa: BLE001
            log.debug("usage.add خطا: %s", exc)

    def record_ai_response(self, response: Any) -> None:
        """بعد از هر generate_content موفق صدا زده شود."""
        prompt = out = 0
        try:
            meta = getattr(response, "usage_metadata", None)
            prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
            out = int(getattr(meta, "candidates_token_count", 0) or 0)
        except Exception:  # noqa: BLE001
            pass
        self.add(ai_requests=1, ai_prompt_tokens=prompt, ai_output_tokens=out)

    def record_ai_error(self) -> None:
        self.add(ai_requests=1, ai_errors=1)

    # ── خواندن ───────────────────────────────────────────────────────────────
    def today(self) -> dict[str, float]:
        return dict(self._days.get(self._today_key(), {}))

    def totals(self, days: int = 1) -> dict[str, float]:
        """جمع n روز اخیر (شامل امروز)."""
        keys = {(self._clock() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(max(1, days))}
        out: dict[str, float] = {c: 0 for c in COUNTERS}
        for k in keys:
            for c, v in self._days.get(k, {}).items():
                if c in out:
                    out[c] += v
        return out

    def cost_usd(self, totals: dict[str, float]) -> float | None:
        """None اگر قیمت تنظیم نشده."""
        if not (self._price_in or self._price_out):
            return None
        return (totals.get("ai_prompt_tokens", 0) * self._price_in
                + totals.get("ai_output_tokens", 0) * self._price_out) / 1_000_000

    # ── گزارش متنی (HTML ساده برای تلگرام/بله) ───────────────────────────────
    def report_lines(self, days: int = 1, *, ai_cap: int | None = None) -> list[str]:
        t = self.totals(days)
        title = "امروز" if days == 1 else f"{days} روز اخیر"
        ai_line = f"🤖 AI ({title}): {int(t['ai_requests'])} درخواست"
        if ai_cap and days == 1:
            ai_line += f" از سقف {ai_cap}"
        if t["ai_errors"]:
            ai_line += f" ({int(t['ai_errors'])} خطا)"
        lines = [
            f"📡 ران‌ها: {int(t['runs'])} | جمع‌آوری: {int(t['collected'])} | جدید: {int(t['added'])} | تکراری: {int(t['duplicates'])}",
            ai_line,
            f"🔤 توکن: ورودی {int(t['ai_prompt_tokens']):,} | خروجی {int(t['ai_output_tokens']):,}",
            f"📨 تلگرام: ✅{int(t['tg_ok'])} ❌{int(t['tg_fail'])} | بله: ✅{int(t['bale_ok'])} ❌{int(t['bale_fail'])}",
        ]
        cost = self.cost_usd(t)
        if cost is not None:
            lines.append(f"💲 هزینهٔ تخمینی AI: ${cost:.4f}")
        if t["runs"]:
            lines.append(f"⏱ میانگین زمان ران: {t['run_seconds'] / t['runs']:.0f}s")
        return lines


# ── singleton ────────────────────────────────────────────────────────────────
_tracker: UsageTracker | None = None


def tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker


def reset_tracker_for_tests(new: UsageTracker | None = None) -> None:
    global _tracker
    _tracker = new
