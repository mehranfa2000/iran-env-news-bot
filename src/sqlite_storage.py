"""
sqlite_storage.py — backend SQLite برای ذخیره‌سازی (مرحله ۲ / آیتم ۱)
نسخه: 4.4.0

- زیرکلاس StorageManager: API، منطق prune و سنگ‌قبر دقیقاً همان است
- مهاجرت خودکار و یک‌باره از news.json + seen_uids.json در اولین باز شدن
  (فایل‌های JSON دست‌نخورده می‌مانند)
- save() = یک تراکنش اتمیک (یا همه نوشته می‌شود یا هیچ)
- journal_mode=DELETE → فقط یک فایل news.db (برای commit در git مناسب‌تر از WAL)
- EXPORT_JSON=true: بعد از هر save، news.json هم برای داشبورد ساخته می‌شود
- فایل DB خراب → StorageCorruptError (مثل JSON؛ هرگز overwrite نمی‌شود)

ستون‌های کلیدی (published_at, category, sent, ...) ستون واقعی‌اند تا بعداً
بتوان با SQL پرس‌وجو کرد؛ tags و pr_analysis به‌صورت JSON ذخیره می‌شوند.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.config import (
    DB_PATH,
    EXPORT_JSON,
    NEWS_JSON_PATH,
    SEEN_UIDS_PATH,
)
from src.storage import (
    _NEWSITEM_FIELDS,
    NewsItem,
    StorageCorruptError,
    StorageManager,
    atomic_write_json,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,  -- ترتیب درج
    uid          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    link         TEXT NOT NULL,
    source       TEXT NOT NULL,
    category     TEXT NOT NULL,
    score        INTEGER NOT NULL,
    published_at TEXT NOT NULL,
    shamsi_date  TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    image_url    TEXT,
    dedicated    INTEGER NOT NULL DEFAULT 1,
    tags         TEXT NOT NULL DEFAULT '[]',
    critical     INTEGER NOT NULL DEFAULT 0,
    ai_summary   TEXT,
    pr_analysis  TEXT,
    sent         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
CREATE INDEX IF NOT EXISTS idx_news_category  ON news(category);
CREATE INDEX IF NOT EXISTS idx_news_sent      ON news(sent);
CREATE TABLE IF NOT EXISTS seen (
    uid          TEXT PRIMARY KEY,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLS = [
    "uid", "title", "link", "source", "category", "score", "published_at",
    "shamsi_date", "summary", "image_url", "dedicated", "tags", "critical",
    "ai_summary", "pr_analysis", "sent",
]
_INSERT = f"INSERT INTO news ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))})"


def _to_row(item: NewsItem) -> tuple[Any, ...]:
    d = asdict(item)
    d["tags"] = json.dumps(d["tags"] or [], ensure_ascii=False)
    d["pr_analysis"] = (
        None if d["pr_analysis"] is None else json.dumps(d["pr_analysis"], ensure_ascii=False)
    )
    d["dedicated"] = int(bool(d["dedicated"]))
    d["critical"] = int(bool(d["critical"]))
    d["sent"] = int(bool(d["sent"]))
    return tuple(d[c] for c in _COLS)


def _from_row(row: sqlite3.Row) -> NewsItem:
    d = {k: row[k] for k in _COLS if k in _NEWSITEM_FIELDS}
    d["tags"] = json.loads(d["tags"] or "[]")
    d["pr_analysis"] = json.loads(d["pr_analysis"]) if d["pr_analysis"] else None
    d["dedicated"] = bool(d["dedicated"])
    d["critical"] = bool(d["critical"])
    d["sent"] = bool(d["sent"])
    return NewsItem(**d)


class SQLiteStorage(StorageManager):
    """جایگزین drop-in برای StorageManager. بعد از کار close() را صدا بزنید."""

    def __init__(
        self,
        db_path: str | Path = DB_PATH,
        *,
        json_path: str | Path = NEWS_JSON_PATH,
        seen_path: str | Path = SEEN_UIDS_PATH,
        export_json: bool = EXPORT_JSON,
        **kwargs: Any,
    ) -> None:
        self._db_path = Path(db_path)
        self._export_json = export_json
        self._conn: sqlite3.Connection | None = None
        # path پایه = news.json (هم منبع مهاجرت هم مقصد export)
        super().__init__(json_path, seen_path=seen_path, **kwargs)

    # ── اتصال ────────────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self._db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except sqlite3.DatabaseError as exc:
            raise StorageCorruptError(
                f"{self._db_path} قابل‌خواندن نیست ({exc}). فایل را از git بازگردانید."
            ) from exc
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _meta(self, key: str) -> str | None:
        row = self._connect().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ── بارگذاری / مهاجرت ────────────────────────────────────────────────────
    def _load_items(self) -> None:
        conn = self._connect()
        try:
            if self._meta("json_imported") is None:
                self._migrate_from_json()
                return
            for row in conn.execute("SELECT * FROM news ORDER BY seq"):
                try:
                    item = _from_row(row)
                except Exception as exc:  # noqa: BLE001
                    log.warning("ردیف نامعتبر در DB نادیده گرفته شد: %s", exc)
                    continue
                self._items[item.uid] = item
            for row in conn.execute("SELECT uid, published_at FROM seen"):
                self._seen[row["uid"]] = row["published_at"]
        except sqlite3.DatabaseError as exc:
            raise StorageCorruptError(f"خطا در خواندن {self._db_path}: {exc}") from exc
        log.info("📂 SQLite: %d خبر، %d سنگ‌قبر", len(self._items), len(self._seen))

    def _load_seen(self) -> None:
        """سنگ‌قبرها همراه _load_items لود می‌شوند."""

    def _migrate_from_json(self) -> None:
        """
        واردسازی یک‌باره از JSON با همان لودر تحمل‌پذیر StorageManager
        (فیلد ناشناخته، تکراری و آیتم نامعتبر را درست مدیریت می‌کند).
        JSON خراب → StorageCorruptError و DB چیزی ثبت نمی‌کند.
        """
        legacy = StorageManager(
            self._path, seen_path=self._seen_path, strict=True, clock=self._clock,
        )
        self._items = dict(legacy._items)
        self._seen = dict(legacy._seen)
        self._write_db()
        conn = self._connect()
        with conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('json_imported', ?)",
                         (self._clock().isoformat(),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)",
                         (str(SCHEMA_VERSION),))
        log.info("🔁 مهاجرت JSON→SQLite کامل شد: %d خبر، %d سنگ‌قبر",
                 len(self._items), len(self._seen))

    # ── ذخیره ────────────────────────────────────────────────────────────────
    def _write_db(self) -> None:
        conn = self._connect()
        with conn:  # تراکنش اتمیک: خطا = rollback
            conn.execute("DELETE FROM news")
            conn.executemany(_INSERT, [_to_row(i) for i in self._items.values()])
            conn.execute("DELETE FROM seen")
            conn.executemany("INSERT INTO seen VALUES (?, ?)", list(self._seen.items()))

    def save(self) -> bool:
        self.prune()
        try:
            self._write_db()
            log.info("💾 news.db ذخیره شد (%d خبر)", len(self._items))
        except sqlite3.Error as exc:
            log.error("❌ خطا در ذخیره news.db: %s", exc)
            return False
        if self._export_json:
            try:
                atomic_write_json(self._path, [asdict(i) for i in self._items.values()])
                atomic_write_json(self._seen_path, self._seen, indent=None)
            except Exception as exc:  # noqa: BLE001
                log.error("❌ export JSON ناموفق: %s", exc)
                return False
        return True

    # ── پرس‌وجوی SQL (برای امکانات بعدی: گزارش، امتیازدهی، ...) ────────────
    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """
        فقط‌خواندنی. توجه: دادهٔ تغییرنکردهٔ حافظه تا save() در DB نیست.
        """
        if not sql.lstrip().lower().startswith(("select", "with")):
            raise ValueError("فقط SELECT مجاز است")
        return list(self._connect().execute(sql, params))
