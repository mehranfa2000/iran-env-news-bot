"""
logging_setup.py — پیکربندی مرکزی logging (C3)
نسخه: 4.3.0

- کنسول (INFO) + فایل با rotation (پیش‌فرض DEBUG، ۵MB × ۳)
- حذف خودکار secretها از لاگ (توکن تلگرام/بله، کلید Gemini، مقدار env های حساس)
  ← مهم: urllib3 در سطح DEBUG آدرس کامل شامل توکن ربات را لاگ می‌کند
- idempotent: چندبار صدا زدن handler تکراری نمی‌سازد
- فقط handlerهای خودش را عوض می‌کند (handlerهای pytest/caplog را دست نمی‌زند)
- خطای ساخت فایل لاگ هرگز برنامه را متوقف نمی‌کند
- زمان در UTC
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import time
from pathlib import Path

from src.config import (
    LOG_BACKUP_COUNT,
    LOG_FILE_LEVEL,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_PATH,
)

_TAG = "_envbot_handler"
_FMT = "%(asctime)sZ | %(levelname)-8s | %(name)-18s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# نام env هایی که مقدارشان نباید هیچ‌وقت در لاگ بیاید
_SECRET_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "BALE_BOT_TOKEN",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
)

# الگوهای عمومی (حتی اگر env تنظیم نشده باشد)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"), "bot<redacted>"),           # آدرس API ربات
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "<redacted-token>"),       # توکن ربات تنها
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "<redacted-key>"),                # کلید Google
    (re.compile(r"(?i)([?&](?:key|api_key|token)=)[^&\s'\"]+"), r"\1<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<redacted-gh-token>"),
)


def _secret_values() -> list[str]:
    """مقدار فعلی secretها (خواندن تازه تا با تغییر env هم کار کند)."""
    vals = [os.environ.get(k, "").strip() for k in _SECRET_ENV_KEYS]
    return [v for v in vals if len(v) >= 8]


def redact(text: str) -> str:
    """حذف secret از یک رشته."""
    for value in _secret_values():
        if value in text:
            text = text.replace(value, "<redacted>")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter که خروجی نهایی (شامل traceback) را پاک‌سازی می‌کند."""

    converter = time.gmtime  # زمان UTC

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def _level(name: str, default: int) -> int:
    value = logging.getLevelName(str(name).upper())
    return value if isinstance(value, int) else default


def _remove_own_handlers(root: logging.Logger) -> None:
    for h in list(root.handlers):
        if getattr(h, _TAG, False):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass


def setup_logging(
    *,
    log_path: str | Path = LOG_PATH,
    console_level: str = LOG_LEVEL,
    file_level: str = LOG_FILE_LEVEL,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
    capture_warnings: bool = True,
    install_excepthook: bool = True,
) -> logging.Logger:
    """
    پیکربندی root logger. چندبار صدا زدن بی‌خطر است.

    مثال:
        from src.logging_setup import setup_logging
        setup_logging()                                  # agent.log
        setup_logging(log_path=DAILY_LOG_PATH)           # در daily_report.py
    """
    root = logging.getLogger()
    _remove_own_handlers(root)

    c_level = _level(console_level, logging.INFO)
    f_level = _level(file_level, logging.DEBUG)
    formatter = RedactingFormatter(fmt=_FMT, datefmt=_DATEFMT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(c_level)
    console.setFormatter(formatter)
    setattr(console, _TAG, True)
    root.addHandler(console)

    file_ok = False
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=max(1024, int(max_bytes)), backupCount=max(0, int(backup_count)),
            encoding="utf-8",
        )
        fh.setLevel(f_level)
        fh.setFormatter(formatter)
        setattr(fh, _TAG, True)
        root.addHandler(fh)
        file_ok = True
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("فایل لاگ ایجاد نشد (%s) — فقط کنسول", exc)

    # root باید به اندازهٔ پرجزئیات‌ترین handler باز باشد
    root.setLevel(min(c_level, f_level) if file_ok else c_level)

    # کتابخانه‌های پرحرف (urllib3 در DEBUG آدرس‌های حاوی توکن را لاگ می‌کند)
    for noisy in ("urllib3", "requests", "feedparser", "google", "grpc", "httpx", "httpcore", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if capture_warnings:
        logging.captureWarnings(True)

    if install_excepthook:
        _install_excepthook()

    return root


def _install_excepthook() -> None:
    """exception کنترل‌نشده هم در فایل لاگ ثبت شود (نه فقط stderr)."""
    if getattr(sys.excepthook, _TAG, False):
        return
    previous = sys.excepthook

    def _hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if not issubclass(exc_type, KeyboardInterrupt):
            logging.getLogger("uncaught").critical("exception کنترل‌نشده", exc_info=(exc_type, exc, tb))
        previous(exc_type, exc, tb)

    setattr(_hook, _TAG, True)
    sys.excepthook = _hook
