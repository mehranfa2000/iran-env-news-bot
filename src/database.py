import requests
import os

class Database:
    def __init__(self):
        self.account_id = os.getenv("CF_ACCOUNT_ID")
        self.api_token = os.getenv("CF_API_TOKEN")
        self.db_id = os.getenv("D1_DATABASE_ID")
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.db_id}/query"
        self.headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

    def execute(self, sql, params=[]):
        payload = {"sql": sql, "params": params}
        response = requests.post(self.url, headers=self.headers, json=payload)
        return response.json()

    def is_duplicate(self, link):
        sql = "SELECT link FROM news WHERE link = ?"
        result = self.execute(sql, [link])
        return len(result.get('result', [{}])[0].get('results', [])) > 0

    def add_news(self, item):
        sql = "INSERT INTO news (title, link, source, category, timestamp) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)"
        self.execute(sql, [item['title'], item['link'], item['source'], item['category']])
