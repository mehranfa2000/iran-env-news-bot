# ============================================================
# مدیریت پایگاه داده Cloudflare D1 - نسخه رفع اشکال شده
# ============================================================

import requests
import os

class Database:
    def __init__(self):
        self.account_id = os.getenv("CF_ACCOUNT_ID")
        self.api_token  = os.getenv("CF_API_TOKEN")
        self.db_id      = os.getenv("D1_DATABASE_ID")
        self.base_url   = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/d1/database/{self.db_id}/query"
        )
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type":  "application/json"
        }

    def execute(self, sql, params=None):
        if params is None:
            params = []
        payload = {"sql": sql, "params": params}
        try:
            resp = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=20
            )
            data = resp.json()
            return data
        except Exception as e:
            print(f"  ❌ خطای دیتابیس: {e}")
            return None  # None برمی‌گردد - باید در همه جا handle شود

    def setup(self):
        """ساخت جداول اولیه"""
        sql = """
        CREATE TABLE IF NOT EXISTS news (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT,
            link        TEXT UNIQUE,
            source      TEXT,
            source_fa   TEXT,
            category    TEXT,
            category_fa TEXT,
            emoji       TEXT,
            score       INTEGER DEFAULT 0,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        result = self.execute(sql)
        if result and result.get("success"):
            print("  ✅ جدول news آماده است.")
        else:
            print(f"  ⚠️ وضعیت setup: {result}")
        return result

    def is_duplicate(self, link):
        """بررسی تکراری بودن خبر - با مدیریت کامل خطا"""
        try:
            sql    = "SELECT id FROM news WHERE link = ? LIMIT 1"
            result = self.execute(sql, [link])

            # اگر خطا داد یا None بود، فرض می‌کنیم تکراری نیست
            if result is None:
                return False

            # ساختار پاسخ Cloudflare D1:
            # {"result": [{"results": [...], "success": true}], "success": true}
            result_list = result.get("result", [])
            if not result_list:
                return False

            first = result_list[0]
            if not isinstance(first, dict):
                return False

            rows = first.get("results", [])
            return len(rows) > 0

        except Exception as e:
            print(f"  ⚠️ خطا در بررسی تکراری: {e}")
            return False  # در صورت خطا، اجازه ارسال بده

    def add_news(self, item):
        """ذخیره خبر جدید"""
        try:
            sql = """
            INSERT OR IGNORE INTO news
                (title, link, source, source_fa, category, category_fa, emoji, score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = [
                item.get("title", "")[:500],
                item.get("link", ""),
                item.get("source", ""),
                item.get("source_fa", ""),
                item.get("category", ""),
                item.get("category_fa", ""),
                item.get("emoji", "🌱"),
                item.get("score", 0)
            ]
            return self.execute(sql, params)
        except Exception as e:
            print(f"  ❌ خطا در ذخیره خبر: {e}")
            return None

    def get_stats(self):
        """آمار کلی برای داشبورد"""
        sql = "SELECT category, category_fa, emoji, count(*) as count FROM news GROUP BY category ORDER BY count DESC"
        return self.execute(sql)

    def get_recent(self, limit=20):
        """آخرین اخبار"""
        sql = f"SELECT * FROM news ORDER BY timestamp DESC LIMIT {limit}"
        return self.execute(sql)
