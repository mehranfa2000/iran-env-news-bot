# ============================================================
# مدیریت پایگاه داده Cloudflare D1
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
                timeout=15
            )
            return resp.json()
        except Exception as e:
            print(f"  ❌ خطای دیتابیس: {e}")
            return {}

    def setup(self):
        """ساخت جداول اولیه (اگر وجود نداشته باشند)"""
        sql = """
        CREATE TABLE IF NOT EXISTS news (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT,
            link      TEXT UNIQUE,
            source    TEXT,
            source_fa TEXT,
            category  TEXT,
            category_fa TEXT,
            emoji     TEXT,
            score     INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        result = self.execute(sql)
        return result

    def is_duplicate(self, link):
        """بررسی تکراری بودن خبر"""
        sql    = "SELECT id FROM news WHERE link = ? LIMIT 1"
        result = self.execute(sql, [link])
        rows   = result.get("result", [{}])[0].get("results", [])
        return len(rows) > 0

    def add_news(self, item):
        """ذخیره خبر جدید در دیتابیس"""
        sql = """
        INSERT OR IGNORE INTO news
            (title, link, source, source_fa, category, category_fa, emoji, score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [
            item.get("title", ""),
            item.get("link", ""),
            item.get("source", ""),
            item.get("source_fa", ""),
            item.get("category", ""),
            item.get("category_fa", ""),
            item.get("emoji", "🌱"),
            item.get("score", 0)
        ]
        return self.execute(sql, params)

    def get_stats(self):
        """آمار کلی برای داشبورد"""
        sql = "SELECT category_fa, emoji, count(*) as count FROM news GROUP BY category"
        return self.execute(sql)

    def get_recent(self, limit=20):
        """آخرین اخبار"""
        sql = f"SELECT * FROM news ORDER BY timestamp DESC LIMIT {limit}"
        return self.execute(sql)
