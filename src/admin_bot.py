"""
admin_bot.py — دستورات ربات برای ادمین (مرحله ۲ / آیتم ۷)
نسخه: 4.7.0

دستورات: /status /stats [روز] /sources /pause [ساعت] /resume /help

معماری (بدون سرور همیشه‌روشن):
  پروژه روی cron در GitHub Actions اجرا می‌شود، پس ربات «poll» می‌کند:
  getUpdates در ابتدای هر ران main.py (و اختیاری: workflow جدا هر ۱۵ دقیقه).
  offset در data/bot_state.json ذخیره می‌شود تا دستور دوبار اجرا نشود.
  → /pause حداکثر از ران بعدی اعمال می‌شود؛ پاسخ‌ها با تأخیر حداکثر یک ران می‌رسند.

امنیت:
- فقط پیام‌های چت ادمین (ADMIN_*_CHAT_ID) پردازش می‌شود؛ بقیه بی‌صدا نادیده گرفته می‌شوند
- اگر ADMIN_USER_IDS تنظیم باشد، فرستنده هم باید در آن فهرست باشد (برای گروه‌ها)
- دستور قدیمی‌تر از COMMAND_MAX_AGE_HOURS اجرا نمی‌شود
- هیچ دستوری داده را حذف نمی‌کند؛ فقط خواندن + pause/resume

CLI:
    python -m src.admin_bot        # یک بار getUpdates و پاسخ
"""
from __future__ import annotations

import html
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from src.config import (
    ADMIN_BALE_CHAT_ID,
    ADMIN_TELEGRAM_CHAT_ID,
    ADMIN_USER_IDS,
    AI_MAX_PER_DAY,
    BALE_API_BASE,
    BALE_BOT_TOKEN,
    BOT_STATE_PATH,
    COMMAND_MAX_AGE_HOURS,
    RSS_FEEDS,
    SOURCE_HEALTH_PATH,
    STATS_JSON_PATH,
    TELEGRAM_API_BASE,
    TELEGRAM_BOT_TOKEN,
)
from src.logging_setup import redact
from src.storage import atomic_write_json
from src.usage import UsageTracker, tracker

log = logging.getLogger(__name__)

_MAX_LEN = 3500
_MAX_PAUSE_HOURS = 24 * 7


def esc(x: object) -> str:
    return html.escape(str(x), quote=False)


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_json(path: str | Path) -> Any:
    try:
        p = Path(path)
        if p.exists() and p.stat().st_size > 0:
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# حالت پایدار ربات (offset + pause)
# ══════════════════════════════════════════════════════════════════════════════
class BotState:
    def __init__(
        self,
        path: str | Path = BOT_STATE_PATH,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.offsets: dict[str, int] = {}
        self.paused = False
        self.paused_until: str | None = None
        self.paused_by = ""
        self.paused_at: str | None = None
        self._load()

    def _load(self) -> None:
        raw = _read_json(self._path)
        if not isinstance(raw, dict):
            return
        offs = raw.get("offsets")
        if isinstance(offs, dict):
            self.offsets = {str(k): int(v) for k, v in offs.items() if isinstance(v, (int, float))}
        self.paused = bool(raw.get("paused"))
        self.paused_until = raw.get("paused_until")
        self.paused_by = str(raw.get("paused_by") or "")
        self.paused_at = raw.get("paused_at")

    def save(self) -> bool:
        try:
            atomic_write_json(self._path, {
                "offsets": self.offsets, "paused": self.paused,
                "paused_until": self.paused_until, "paused_by": self.paused_by,
                "paused_at": self.paused_at,
            })
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("bot_state.json ذخیره نشد: %s", exc)
            return False

    def is_paused(self) -> bool:
        """pause با مدت تمام‌شده خودکار برداشته می‌شود (حالت در save بعدی ثبت می‌شود)."""
        if not self.paused:
            return False
        until = _parse_dt(self.paused_until)
        if until is not None and until <= self._clock():
            self.paused, self.paused_until = False, None
            return False
        return True

    def pause(self, hours: float | None, by: str) -> None:
        now = self._clock()
        self.paused, self.paused_by, self.paused_at = True, by, now.isoformat()
        self.paused_until = (now + timedelta(hours=hours)).isoformat() if hours else None

    def resume(self) -> bool:
        was = self.is_paused()
        self.paused, self.paused_until = False, None
        return was


# ══════════════════════════════════════════════════════════════════════════════
# قالب پاسخ‌ها (توابع خالص → قابل‌تست)
# ══════════════════════════════════════════════════════════════════════════════
HELP_TEXT = (
    "🤖 <b>دستورات ادمین</b>\n"
    "/status — وضعیت کلی سامانه\n"
    "/stats [روز] — مصرف و آمار (پیش‌فرض امروز، حداکثر ۳۰ روز)\n"
    "/sources — وضعیت منابع RSS\n"
    "/pause [ساعت] — توقف جمع‌آوری/ارسال (بدون عدد: تا /resume)\n"
    "/resume — ادامهٔ کار\n"
    "ℹ️ دستورات در ابتدای هر ران بررسی می‌شوند؛ ممکن است تا یک ساعت تأخیر داشته باشند."
)


def _age(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "نامشخص"
    mins = (now - dt).total_seconds() / 60
    return f"{mins:.0f} دقیقه پیش" if mins < 90 else f"{mins / 60:.1f} ساعت پیش"


def fmt_status(stats: dict | None, state: BotState, health: dict | None, now: datetime) -> str:
    stats = stats or {}
    lines = ["🌿 <b>وضعیت سامانه</b>"]
    if state.is_paused():
        until = f" تا {esc((state.paused_until or '')[:16])}Z" if state.paused_until else " (تا /resume)"
        lines.append(f"⏸ <b>متوقف</b>{until}")
    else:
        lines.append("▶️ فعال")

    last = _parse_dt(stats.get("last_run"))
    icon = {"ok": "✅", "paused": "⏸"}.get(stats.get("status"), "❌")
    lines.append(f"{icon} آخرین ران: {_age(last, now)} — {esc(stats.get('status', '؟'))}")
    lines.append(
        f"📡 {stats.get('last_run_collected', 0)} جمع | 🔍 {stats.get('last_run_filtered', 0)} فیلتر | "
        f"🔁 {stats.get('last_run_duplicates', 0)} تکراری | 💾 {stats.get('last_run_added', 0)} جدید | "
        f"📨 {stats.get('last_run_sent', 0)} ارسال | ❌ {stats.get('last_run_failed', 0)}"
    )
    lines.append(f"🗂 ذخیره‌شده: {stats.get('total_news_stored', 0)} خبر")

    names = [f.name for f in RSS_FEEDS]
    disabled = [n for n in names if _is_disabled((health or {}).get(n), now)]
    lines.append(f"📰 منابع: {len(names) - len(disabled)}/{len(names)} فعال"
                 + (f" — غیرفعال: {esc('، '.join(disabled[:5]))}" if disabled else ""))

    used = stats.get("ai_used_today", 0) if stats.get("ai_date") == now.strftime("%Y-%m-%d") else 0
    lines.append(f"🤖 AI امروز: {used}/{AI_MAX_PER_DAY}")
    return "\n".join(lines)


def _is_disabled(st: dict | None, now: datetime) -> bool:
    until = _parse_dt((st or {}).get("disabled_until"))
    return until is not None and until > now


def fmt_sources(health: dict | None, now: datetime) -> str:
    health = health or {}
    lines = ["📰 <b>منابع RSS</b>"]
    for f in RSS_FEEDS[:40]:
        st = health.get(f.name)
        if not st:
            lines.append(f"▫️ {esc(f.name)} — هنوز ثبت نشده")
            continue
        if _is_disabled(st, now):
            icon = "⏸"
            extra = f"تا {str(st.get('disabled_until'))[:16]}Z — {st.get('last_error', '')}"
        elif st.get("consecutive_failures", 0) > 0:
            icon = "⚠️"
            extra = f"{st['consecutive_failures']} خطای پیاپی — {st.get('last_error', '')}"
        else:
            icon = "✅"
            extra = f"{int(st.get('last_count', 0))} خبر، {int(st.get('avg_latency_ms', 0))}ms"
        lines.append(f"{icon} {esc(f.name)} — {esc(extra)}")
    return "\n".join(lines)


def fmt_stats(usage: UsageTracker, days: int) -> str:
    days = max(1, min(30, days))
    return "📊 <b>آمار و مصرف</b>\n" + "\n".join(usage.report_lines(days, ai_cap=AI_MAX_PER_DAY))


# ══════════════════════════════════════════════════════════════════════════════
# ربات
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class _Channel:
    name: str            # telegram | bale
    base: str            # https://api.../bot<TOKEN>
    admin_chat: str


def _default_http(method: str, url: str, data: dict[str, Any], timeout: int) -> dict | None:
    try:
        if method == "GET":
            resp = requests.get(url, params=data, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("admin_bot HTTP خطا: %s", type(exc).__name__)   # URL حاوی توکن است
        return None


class AdminBot:
    def __init__(
        self,
        *,
        state: BotState | None = None,
        usage: UsageTracker | None = None,
        channels: list[_Channel] | None = None,
        user_ids: list[str] | None = None,
        stats_path: str | Path = STATS_JSON_PATH,
        health_path: str | Path = SOURCE_HEALTH_PATH,
        max_age_hours: float = COMMAND_MAX_AGE_HOURS,
        http: Callable[[str, str, dict[str, Any], int], dict | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.state = state or BotState()
        self._usage = usage
        self._user_ids = [str(u) for u in (ADMIN_USER_IDS if user_ids is None else user_ids)]
        self._stats_path, self._health_path = stats_path, health_path
        self._max_age = timedelta(hours=max_age_hours)
        self._http = http or _default_http
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if channels is None:
            channels = []
            if TELEGRAM_BOT_TOKEN and ADMIN_TELEGRAM_CHAT_ID:
                channels.append(_Channel("telegram", f"{TELEGRAM_API_BASE}{TELEGRAM_BOT_TOKEN}", ADMIN_TELEGRAM_CHAT_ID))
            if BALE_BOT_TOKEN and ADMIN_BALE_CHAT_ID:
                channels.append(_Channel("bale", f"{BALE_API_BASE}{BALE_BOT_TOKEN}", ADMIN_BALE_CHAT_ID))
        self._channels = channels

    @property
    def enabled(self) -> bool:
        return bool(self._channels)

    # ── polling ──────────────────────────────────────────────────────────────
    def poll_once(self) -> int:
        """تعداد دستورهای اجراشده. هرگز exception نمی‌دهد."""
        handled = 0
        for ch in self._channels:
            try:
                handled += self._poll_channel(ch)
            except Exception as exc:  # noqa: BLE001
                log.warning("poll %s خطا: %s", ch.name, type(exc).__name__)
            finally:
                self.state.save()
        return handled

    def _poll_channel(self, ch: _Channel) -> int:
        offset = self.state.offsets.get(ch.name, 0)
        data = self._http("GET", f"{ch.base}/getUpdates", {"offset": offset, "limit": 50, "timeout": 0}, 15)
        if not data or not data.get("ok"):
            desc = (data or {}).get("description", "بدون پاسخ")
            log.warning("getUpdates[%s] ناموفق: %s", ch.name, redact(str(desc))[:120])
            return 0
        handled = 0
        for upd in data.get("result", []):
            try:
                uid = int(upd["update_id"])
                self.state.offsets[ch.name] = max(self.state.offsets.get(ch.name, 0), uid + 1)
                if self._handle_update(ch, upd):
                    handled += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("update نامعتبر: %s", type(exc).__name__)
            self.state.save()   # offset بعد از هر update: دستور هرگز دوبار اجرا نشود
        return handled

    # ── پردازش ───────────────────────────────────────────────────────────────
    def _authorized(self, ch: _Channel, msg: dict) -> bool:
        if str(msg.get("chat", {}).get("id")) != str(ch.admin_chat):
            return False
        if self._user_ids and str(msg.get("from", {}).get("id")) not in self._user_ids:
            return False
        return True

    def _handle_update(self, ch: _Channel, upd: dict) -> bool:
        msg = upd.get("message")
        if not isinstance(msg, dict) or not self._authorized(ch, msg):
            return False
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return False
        ts = msg.get("date")
        if isinstance(ts, (int, float)):
            if self._clock() - datetime.fromtimestamp(ts, timezone.utc) > self._max_age:
                log.info("دستور قدیمی نادیده گرفته شد")
                return False

        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        who = str(msg.get("from", {}).get("username") or msg.get("from", {}).get("id") or "admin")
        reply = self.execute(cmd, args, who)
        if reply is None:
            return False
        self._reply(ch, msg["chat"]["id"], reply)
        log.info("دستور ادمین اجرا شد: %s", cmd)
        return True

    def execute(self, cmd: str, args: list[str], who: str = "admin") -> str | None:
        """منطق دستورها (بدون شبکه). None = دستور ناشناخته."""
        now = self._clock()
        if cmd in ("/start", "/help"):
            return HELP_TEXT
        if cmd == "/status":
            return fmt_status(_read_json(self._stats_path), self.state,
                              _read_json(self._health_path), now)
        if cmd == "/sources":
            return fmt_sources(_read_json(self._health_path), now)
        if cmd == "/stats":
            days = 1
            if args:
                try:
                    days = int(args[0])
                except ValueError:
                    return "❌ فرمت: /stats [تعداد روز]"
            return fmt_stats(self._usage or tracker(), days)
        if cmd == "/pause":
            hours: float | None = None
            if args:
                try:
                    hours = float(args[0])
                except ValueError:
                    return "❌ فرمت: /pause [ساعت]"
                if not 0 < hours <= _MAX_PAUSE_HOURS:
                    return f"❌ ساعت باید بین ۰ و {_MAX_PAUSE_HOURS} باشد"
            self.state.pause(hours, who)
            until = f"برای {hours:g} ساعت" if hours else "تا /resume"
            return f"⏸ سامانه متوقف شد ({until}). از ران بعدی اعمال می‌شود."
        if cmd == "/resume":
            return "▶️ از سر گرفته شد." if self.state.resume() else "ℹ️ سامانه متوقف نبود."
        return None

    def _reply(self, ch: _Channel, chat_id: Any, text: str) -> None:
        text = redact(text)
        if len(text) > _MAX_LEN:
            text = text[: _MAX_LEN - 1] + "…"
        self._http("POST", f"{ch.base}/sendMessage",
                   {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": True}, 15)


def main() -> int:
    from src.logging_setup import setup_logging

    setup_logging()
    bot = AdminBot()
    if not bot.enabled:
        print("❌ چت ادمین/توکن تنظیم نیست")
        return 1
    n = bot.poll_once()
    print(f"✅ {n} دستور پردازش شد")
    return 0


if __name__ == "__main__":
    sys.exit(main())
