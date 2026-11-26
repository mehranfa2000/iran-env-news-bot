#!/usr/bin/env python3
"""
healthcheck.py — بررسی سلامت سامانه (C4)
نسخه: 4.3.0

فقط کتابخانهٔ استاندارد؛ بدون نیاز به pip install.

اجرا:
    python healthcheck.py                # گزارش متنی
    python healthcheck.py --json         # خروجی ماشین‌خوان
    python healthcheck.py --strict       # هشدار هم = شکست
    python healthcheck.py --network      # تست زندهٔ getMe تلگرام/بله (توکن چاپ نمی‌شود)
    python healthcheck.py --require-env  # نبودن secret = شکست (در حالت عادی هشدار)

کد خروج:
    0  سالم (ممکن است هشدار داشته باشد)
    1  حداقل یک بررسی شکست خورده
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OK, WARN, FAIL = "ok", "warn", "fail"
_ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}

NEWS_REQUIRED = ("uid", "title", "link", "source", "category", "score", "published_at", "shamsi_date")
STATS_REQUIRED = (
    "last_run", "last_run_collected", "last_run_filtered", "last_run_sent",
    "last_run_failed", "total_news_stored", "ai_date", "ai_used_today", "status",
)


@dataclass
class Check:
    name: str
    status: str
    detail: str


# ──────────────────────────────────────────────────────────────────────────────
# کمکی‌ها
# ──────────────────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_hours(dt: datetime) -> float:
    return (_now() - dt).total_seconds() / 3600


def _load_json(path: Path) -> tuple[Any, str | None]:
    """(data, error). error=None یعنی موفق."""
    if not path.exists():
        return None, "فایل وجود ندارد"
    if path.stat().st_size == 0:
        return None, "فایل خالی است"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"JSON نامعتبر: {exc}"


def _fmt_age(hours: float) -> str:
    return f"{hours * 60:.0f} دقیقه" if hours < 1 else f"{hours:.1f} ساعت"


# ──────────────────────────────────────────────────────────────────────────────
# بررسی‌ها
# ──────────────────────────────────────────────────────────────────────────────
def check_data_dir(cfg: Any) -> list[Check]:
    data_dir = Path(cfg.DATA_DIR)
    if not data_dir.is_dir():
        return [Check("data_dir", FAIL, f"پوشهٔ {data_dir} وجود ندارد")]
    out: list[Check] = []
    if not os.access(data_dir, os.W_OK):
        out.append(Check("data_dir", FAIL, "پوشهٔ data قابل‌نوشتن نیست"))
    else:
        out.append(Check("data_dir", OK, str(data_dir)))
    free_mb = shutil.disk_usage(data_dir).free / (1024 * 1024)
    status = OK if free_mb >= cfg.HEALTH_MIN_DISK_MB else WARN
    out.append(Check("disk", status, f"{free_mb:.0f}MB آزاد (حداقل {cfg.HEALTH_MIN_DISK_MB}MB)"))
    return out


def check_news(cfg: Any) -> list[Check]:
    path = Path(cfg.NEWS_JSON_PATH)
    data, err = _load_json(path)
    if err:
        # اولین اجرا: فایل هنوز نیست → هشدار؛ خراب بودن → شکست
        status = WARN if err in ("فایل وجود ندارد", "فایل خالی است") else FAIL
        return [Check("news.json", status, err)]
    if not isinstance(data, list):
        return [Check("news.json", FAIL, "ریشهٔ JSON باید لیست باشد")]

    out: list[Check] = []
    bad = 0
    uids: set[str] = set()
    dupes = 0
    newest: datetime | None = None
    for entry in data:
        if not isinstance(entry, dict) or any(k not in entry for k in NEWS_REQUIRED):
            bad += 1
            continue
        if entry["uid"] in uids:
            dupes += 1
        uids.add(entry["uid"])
        dt = _parse_dt(entry.get("published_at"))
        if dt and (newest is None or dt > newest):
            newest = dt

    detail = f"{len(data)} خبر"
    if newest:
        detail += f"، جدیدترین: {_fmt_age(_age_hours(newest))} پیش"
    out.append(Check("news.json", OK, detail))

    if bad:
        out.append(Check("news.schema", WARN, f"{bad} آیتم فیلد اجباری ندارد"))
    if dupes:
        out.append(Check("news.uid", WARN, f"{dupes} uid تکراری"))
    if len(data) > cfg.MAX_STORED_NEWS * 1.2:
        out.append(Check("news.cap", WARN, f"{len(data)} خبر؛ سقف {cfg.MAX_STORED_NEWS} (pruning اجرا نشده؟)"))
    return out


def check_run_stats(cfg: Any) -> list[Check]:
    path = Path(cfg.STATS_JSON_PATH)
    data, err = _load_json(path)
    if err:
        status = WARN if err in ("فایل وجود ندارد", "فایل خالی است") else FAIL
        return [Check("run_stats", status, err)]
    if not isinstance(data, dict):
        return [Check("run_stats", FAIL, "ریشهٔ JSON باید dict باشد")]

    out: list[Check] = []
    missing = [k for k in STATS_REQUIRED if k not in data]
    if missing:
        out.append(Check("run_stats.schema", WARN, "کلیدهای ناقص: " + ", ".join(missing)))

    # تازگی آخرین ران ← مهم‌ترین بررسی (cron متوقف شده؟)
    last = _parse_dt(data.get("last_run"))
    if last is None:
        out.append(Check("last_run", FAIL, "زمان آخرین ران نامعتبر یا ناموجود"))
    else:
        age = _age_hours(last)
        limit = cfg.HEALTH_MAX_RUN_AGE_HOURS
        status = OK if age <= limit else FAIL
        out.append(Check("last_run", status, f"{_fmt_age(age)} پیش (حداکثر مجاز {limit:g} ساعت)"))

    status_val = data.get("status")
    out.append(Check("last_status", OK if status_val == "ok" else FAIL, f"status={status_val!r}"))

    sent, failed = data.get("last_run_sent", 0), data.get("last_run_failed", 0)
    if isinstance(failed, int) and isinstance(sent, int) and failed > 0:
        ratio_bad = failed >= max(1, sent)
        out.append(Check("send", WARN if ratio_bad else OK, f"آخرین ران: موفق={sent}، ناموفق={failed}"))

    used, cap = data.get("ai_used_today"), cfg.AI_MAX_PER_DAY
    if isinstance(used, int):
        if data.get("ai_date") != _now().strftime("%Y-%m-%d"):
            out.append(Check("ai_quota", OK, f"سهمیه امروز مصرف نشده (آخرین ثبت: {data.get('ai_date')})"))
        else:
            out.append(Check("ai_quota", WARN if used > cap else OK, f"{used}/{cap} امروز"))
    return out


def check_daily_report(cfg: Any) -> list[Check]:
    path = Path(cfg.DAILY_JSON_PATH)
    data, err = _load_json(path)
    if err:
        return [Check("daily_analysis", WARN, err)]
    gen = _parse_dt(data.get("generated_at_utc")) if isinstance(data, dict) else None
    if gen is None:
        return [Check("daily_analysis", WARN, "generated_at_utc نامعتبر")]
    age = _age_hours(gen)
    limit = cfg.HEALTH_MAX_REPORT_AGE_HOURS
    return [Check("daily_analysis", OK if age <= limit else WARN, f"{_fmt_age(age)} پیش (حداکثر {limit:g} ساعت)")]


def check_log(cfg: Any) -> list[Check]:
    path = Path(cfg.LOG_PATH)
    if not path.exists():
        return [Check("log", WARN, "agent.log هنوز ساخته نشده")]
    size_mb = path.stat().st_size / (1024 * 1024)
    limit = cfg.LOG_MAX_BYTES / (1024 * 1024) * 1.5
    return [Check("log", OK if size_mb <= limit else WARN, f"{size_mb:.2f}MB")]


def check_env(cfg: Any, require: bool) -> list[Check]:
    """فقط وجود secret بررسی می‌شود؛ مقدار هرگز چاپ نمی‌شود."""
    miss = FAIL if require else WARN
    out: list[Check] = []
    tg = bool(cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_CHANNEL_ID)
    bale = bool(cfg.BALE_BOT_TOKEN and cfg.BALE_CHANNEL_ID)
    if tg or bale:
        names = [n for n, ok in (("تلگرام", tg), ("بله", bale)) if ok]
        out.append(Check("env.send", OK, "پیکربندی‌شده: " + " + ".join(names)))
    else:
        out.append(Check("env.send", miss, "نه تلگرام و نه بله کامل تنظیم نیست (TOKEN + CHANNEL_ID)"))
    # توکن بدون channel (یا برعکس) معمولاً اشتباه تایپی است
    for label, token, chan in (
        ("تلگرام", cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHANNEL_ID),
        ("بله", cfg.BALE_BOT_TOKEN, cfg.BALE_CHANNEL_ID),
    ):
        if bool(token) != bool(chan):
            out.append(Check(f"env.{label}", WARN, "فقط یکی از TOKEN/CHANNEL_ID تنظیم شده"))
    out.append(Check("env.gemini", OK if cfg.GEMINI_API_KEY else miss,
                     "GEMINI_API_KEY تنظیم است" if cfg.GEMINI_API_KEY else "GEMINI_API_KEY تنظیم نیست"))
    return out


def _get_me(base: str, token: str, timeout: float = 10.0) -> tuple[bool, str]:
    url = f"{base}{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        return bool(body.get("ok")), "ok" if body.get("ok") else "پاسخ ok=false"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        # پیام exception ممکن است URL (با توکن) داشته باشد → فقط نوع خطا
        return False, type(exc).__name__


def check_network(cfg: Any) -> list[Check]:
    out: list[Check] = []
    for label, base, token in (
        ("تلگرام", cfg.TELEGRAM_API_BASE, cfg.TELEGRAM_BOT_TOKEN),
        ("بله", cfg.BALE_API_BASE, cfg.BALE_BOT_TOKEN),
    ):
        if not token:
            continue
        ok, msg = _get_me(base, token)
        out.append(Check(f"net.{label}", OK if ok else FAIL, f"getMe: {msg}"))
    if not out:
        out.append(Check("net", WARN, "توکنی برای تست شبکه نیست"))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# اجرا
# ──────────────────────────────────────────────────────────────────────────────
def run_checks(*, network: bool = False, require_env: bool = False) -> list[Check]:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import logging

        logging.disable(logging.WARNING)  # هشدارهای import کانفیگ در خروجی healthcheck نیاید
        try:
            from src import config as cfg
        finally:
            logging.disable(logging.NOTSET)
    except Exception as exc:  # noqa: BLE001
        return [Check("config", FAIL, f"import نشد: {type(exc).__name__}: {exc}")]

    checks: list[Check] = [Check("config", OK, "import موفق")]
    for fn in (check_data_dir, check_news, check_run_stats, check_daily_report, check_log):
        try:
            checks.extend(fn(cfg))
        except Exception as exc:  # noqa: BLE001 — خود healthcheck نباید crash کند
            checks.append(Check(fn.__name__, FAIL, f"خطای داخلی: {type(exc).__name__}: {exc}"))
    checks.extend(check_env(cfg, require_env))
    if network:
        checks.extend(check_network(cfg))
    return checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="healthcheck سامانه پایش محیط‌زیست")
    ap.add_argument("--json", action="store_true", help="خروجی JSON")
    ap.add_argument("--strict", action="store_true", help="هشدار هم شکست حساب شود")
    ap.add_argument("--network", action="store_true", help="تست زندهٔ getMe")
    ap.add_argument("--require-env", action="store_true", help="نبودن secret = شکست")
    args = ap.parse_args(argv)

    checks = run_checks(network=args.network, require_env=args.require_env)
    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    healthy = not failed and not (args.strict and warned)

    if args.json:
        print(json.dumps(
            {
                "healthy": healthy,
                "checked_at": _now().isoformat(),
                "checks": [c.__dict__ for c in checks],
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print("🩺 healthcheck — سامانه پایش هوشمند محیط‌زیست")
        print("─" * 56)
        for c in checks:
            print(f"{_ICON[c.status]} {c.name:<18} {c.detail}")
        print("─" * 56)
        print(f"نتیجه: {'سالم' if healthy else 'ناسالم'} — "
              f"{len(failed)} شکست، {len(warned)} هشدار، {len(checks) - len(failed) - len(warned)} موفق")

    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
