"""
alerts.py — هشدار خطا به ادمین (مرحله ۲ / آیتم ۵)
نسخه: 4.6.0

کانال: پیام خصوصی/گروه ادمین در تلگرام و/یا بله
  (همان TELEGRAM_BOT_TOKEN / BALE_BOT_TOKEN + ADMIN_*_CHAT_ID).
  ادمین باید یک‌بار به ربات /start بزند.

ضداسپم با «حالت هشدار»:
  fire(key, text)    اولین بار فوراً می‌فرستد؛ تا وقتی مشکل ادامه دارد فقط
                     هر ALERT_REPEAT_HOURS ساعت یادآوری می‌کند
  resolve(key, text) فقط اگر قبلاً هشدار فعال بوده یک بار «رفع شد» می‌فرستد

اصول:
- هیچ‌وقت exception بالا نمی‌دهد (هشدار نباید ران را بشکند)
- اگر ارسال شکست خورد، حالت ثبت نمی‌شود → ران بعد دوباره تلاش می‌کند
- متن قبل از ارسال از secretها پاک می‌شود
- بدون چت ادمین: فقط لاگ

CLI:
    python -m src.alerts --test
    python -m src.alerts --message "متن"
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from src.config import (
    ADMIN_BALE_CHAT_ID,
    ADMIN_TELEGRAM_CHAT_ID,
    ALERT_REPEAT_HOURS,
    ALERT_STATE_PATH,
    ALERT_TIMEOUT_SEC,
    BALE_API_BASE,
    BALE_BOT_TOKEN,
    TELEGRAM_API_BASE,
    TELEGRAM_BOT_TOKEN,
)
from src.logging_setup import redact
from src.storage import atomic_write_json

log = logging.getLogger(__name__)

_MAX_LEN = 3500   # زیر سقف ۴۰۹۶ تلگرام


def esc(text: object) -> str:
    """escape برای parse_mode=HTML."""
    return html.escape(str(text), quote=False)


def run_url() -> str:
    """لینک ران GitHub Actions (خالی اگر خارج از Actions)."""
    server, repo, run = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else ""


def _default_post(url: str, payload: dict[str, Any], timeout: int) -> bool:
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.status_code == 200 and bool(resp.json().get("ok", True))
    except Exception as exc:  # noqa: BLE001
        # پیام exception ممکن است URL حاوی توکن باشد → فقط نوع خطا
        log.warning("ارسال هشدار ناموفق: %s", type(exc).__name__)
        return False


class AdminNotifier:
    def __init__(
        self,
        *,
        state_path: str | Path = ALERT_STATE_PATH,
        repeat_hours: float = ALERT_REPEAT_HOURS,
        telegram: tuple[str, str] | None = None,   # (token, chat_id)
        bale: tuple[str, str] | None = None,
        timeout: int = ALERT_TIMEOUT_SEC,
        clock: Callable[[], datetime] | None = None,
        post: Callable[[str, dict[str, Any], int], bool] | None = None,
    ) -> None:
        self._path = Path(state_path)
        self._repeat = max(0.0, float(repeat_hours))
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._post = post or _default_post

        tg = telegram if telegram is not None else (TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_CHAT_ID)
        bl = bale if bale is not None else (BALE_BOT_TOKEN, ADMIN_BALE_CHAT_ID)
        self._channels: list[tuple[str, str]] = []   # (url، chat_id)
        if tg[0] and tg[1]:
            self._channels.append((f"{TELEGRAM_API_BASE}{tg[0]}/sendMessage", tg[1]))
        if bl[0] and bl[1]:
            self._channels.append((f"{BALE_API_BASE}{bl[0]}/sendMessage", bl[1]))

        self._state: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    @property
    def enabled(self) -> bool:
        return bool(self._channels)

    # ── حالت ─────────────────────────────────────────────────────────────────
    def _load(self) -> None:
        import json

        try:
            if self._path.exists() and self._path.stat().st_size > 0:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._state = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception as exc:  # noqa: BLE001
            log.warning("alert_state.json خوانده نشد (%s) — از صفر", exc)

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            atomic_write_json(self._path, self._state)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            log.warning("alert_state.json ذخیره نشد: %s", exc)

    def is_active(self, key: str) -> bool:
        return bool(self._state.get(key, {}).get("active"))

    # ── ارسال ────────────────────────────────────────────────────────────────
    def send_now(self, text: str) -> bool:
        """ارسال بی‌قید‌وشرط. True اگر حداقل یک کانال موفق بود."""
        text = redact(text)
        if len(text) > _MAX_LEN:
            text = text[: _MAX_LEN - 1] + "…"
        if not self.enabled:
            log.warning("📣 هشدار (چت ادمین تنظیم نیست): %s", text.replace("\n", " | ")[:300])
            return False
        ok = False
        for url, chat in self._channels:
            payload = {"chat_id": chat, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}
            ok = self._post(url, payload, self._timeout) or ok
        return ok

    def fire(self, key: str, text: str) -> bool:
        """هشدار مشکل. True اگر پیام واقعاً ارسال شد."""
        try:
            st = self._state.get(key, {})
            now = self._clock()
            if st.get("active"):
                last = st.get("last_sent")
                try:
                    age_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600
                except (TypeError, ValueError):
                    age_h = float("inf")
                if age_h < self._repeat:
                    return False
                text = "🔁 <b>یادآوری (ادامه دارد)</b>\n" + text
            if not self.send_now(text):
                return False
            self._state[key] = {"active": True, "last_sent": now.isoformat()}
            self._dirty = True
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("fire(%s) خطا: %s", key, type(exc).__name__)
            return False

    def resolve(self, key: str, text: str) -> bool:
        """اگر هشدار فعال بود یک‌بار «رفع شد» بفرست و حالت را پاک کن."""
        try:
            if not self.is_active(key):
                return False
            if not self.send_now(text):
                return False   # بعداً دوباره تلاش می‌شود
            self._state.pop(key, None)
            self._dirty = True
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("resolve(%s) خطا: %s", key, type(exc).__name__)
            return False


# ── قالب پیام‌ها ─────────────────────────────────────────────────────────────
def _footer() -> str:
    url = run_url()
    return f"\n🔗 {esc(url)}" if url else ""


def msg_run_failed(error: str) -> str:
    return f"🚨 <b>اجرای سامانه شکست خورد</b>\n<code>{esc(error)[:600]}</code>{_footer()}"


def msg_run_recovered() -> str:
    return "✅ <b>اجرای سامانه به حالت عادی برگشت</b>"


def msg_source_disabled(feed: str, detail: str) -> str:
    return f"⏸ <b>منبع غیرفعال شد</b>\n{esc(feed)}\n{esc(detail)}"


def msg_source_recovered(feed: str, detail: str) -> str:
    return f"✅ <b>منبع دوباره سالم شد</b>\n{esc(feed)} — {esc(detail)}"


def msg_collect_empty(n_feeds: int) -> str:
    return (f"⚠️ <b>هیچ فیدی خبر نداد</b> ({n_feeds} فید)\n"
            "احتمالاً مشکل شبکه یا مسدودشدن IP است." + _footer())


def msg_send_failed(failed: int) -> str:
    return (f"⚠️ <b>ارسال به کانال ناموفق</b> ({failed} خبر)\n"
            "توکن/دسترسی ربات یا شبکه را بررسی کنید." + _footer())


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ارسال پیام به ادمین")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--test", action="store_true", help="پیام آزمایشی")
    g.add_argument("--message", help="متن پیام (HTML ساده)")
    args = ap.parse_args(argv)

    n = AdminNotifier()
    if not n.enabled:
        print("❌ چت ادمین یا توکن ربات تنظیم نیست (ADMIN_TELEGRAM_CHAT_ID / ADMIN_BALE_CHAT_ID)")
        return 1
    text = "🧪 پیام آزمایشی سامانه پایش — هشدارها فعال است." if args.test else args.message
    ok = n.send_now(text)
    print("✅ ارسال شد" if ok else "❌ ارسال ناموفق")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
