import requests
import os

def send_to_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_to_bale(token, chat_id, text):
    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Bale Error: {e}")

def format_message(item):
    # قالب‌بندی پیام خروجی
    msg = (
        f"{item['emoji']} <b>{item['title']}</b>\n\n"
        f"🔹 {item['summary'][:200]}...\n\n"
        f"🌐 منبع: {item['source']}\n"
        f"🔗 متن کامل: {item['link']}\n\n"
        f"☘️ @EnvironmentalNewsIran" # آیدی کانال خود را اینجا هم می‌توانید بنویسید
    )
    return msg
