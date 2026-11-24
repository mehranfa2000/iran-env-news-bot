# src/sender.py
"""
ارسال اخبار به کانال‌های تلگرام و بله
photo + caption HTML + inline keyboard
نسخه ۴.۰
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from agent import NewsItem, PRAnalysis
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    BALE_BOT_TOKEN,
    BALE_CHANNEL_ID,
    TELEGRAM_API_BASE,
    BALE_API_BASE,
    TELEGRAM_CAPTION_MAX,
    BALE_CAPTION_MAX,
    DELAY_BETWEEN_SENDS,
    BOT_SIGNATURE,
    CATEGORIES,
)

logger = logging.getLogger("sender")

REQUEST_TIMEOUT = 20


# ══════════════════════════════════════════════════════════════════
# ساخت کپشن HTML
# ══════════════════════════════════════════════════════════════════

def _build_caption(item: NewsItem, max_len: int = 1024) -> str:
    cat = CATEGORIES.get(item.category, {})
    cat_emoji = cat.get("emoji", "🌿")
    cat_label = cat.get("label", item.category)

    critical_badge = "🔴 <b>بحرانی</b> | " if item.is_critical else ""

    lines = [
        f"{critical_badge}{cat_emoji} <b>{cat_label}</b>",
        "",
        f"📰 <b>{item.title}</b>",
    ]

    # خلاصه AI یا خلاصه معمولی
    summary_text = item.ai_summary or item.summary
    if summary_text:
        lines += ["", f"📋 {summary_text[:300]}"]

    # فیلدهای تحلیل بحرانی
    if item.is_critical and item.pr_analysis:
        pr: PRAnalysis = item.pr_analysis
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>تحلیل روابط‌عمومی</b>",
            f"⚡ فوریت: <b>{pr.urgency}</b>",
            f"🎭 احساس: {pr.sentiment}",
            f"⚠️ حساسیت: {pr.sensitivity}",
            f"📺 ریسک رسانه‌ای: {pr.media_risk}",
            f"🎯 اقدام: {pr.action[:150]}",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

    lines += [
        "",
        f"📡 منبع: {item.source}",
        f"🗓 {item.shamsi_date}  ⏰ {item.shamsi_time}",
        BOT_SIGNATURE,
    ]

    caption = "\n".join(lines)

    # برش هوشمند
    if len(caption) > max_len:
        caption = caption[: max_len - 3] + "..."

    return caption


# ══════════════════════════════════════════════════════════════════
# ساخت inline keyboard
# ══════════════════════════════════════════════════════════════════

def _build_keyboard(item: NewsItem) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📖 مطالعه کامل خبر",
                    "url": item.link,
                }
            ]
        ]
    }


# ══════════════════════════════════════════════════════════════════
# ارسال به یک پلتفرم
# ══════════════════════════════════════════════════════════════════

def _send_to_platform(
    api_base: str,
    token: str,
    chat_id: str,
    item: NewsItem,
    max_cap: int,
    platform_name: str,
) -> bool:
    """ارسال photo+caption یا fallback به text"""
    if not token or not chat_id:
        logger.warning("⚠️ %s: توکن یا chat_id تنظیم نشده", platform_name)
        return False

    base_url = f"{api_base}{token}"
    caption = _build_caption(item, max_cap)
    keyboard = _build_keyboard(item)

    # ── تلاش ۱: sendPhoto ──
    if item.image_url:
        try:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                json={
                    "chat_id": chat_id,
                    "photo": item.image_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
                timeout=REQUEST_TIMEOUT,
            )
            data = resp.json()
            if data.get("ok"):
                logger.info("📸 %s ✅ photo: %s", platform_name, item.title[:40])
                return True
            else:
                logger.warning(
                    "⚠️ %s sendPhoto خطا: %s",
                    platform_name,
                    data.get("description", ""),
                )
        except Exception as e:
            logger.warning("⚠️ %s sendPhoto exception: %s", platform_name, e)

    # ── تلاش ۲: sendMessage (fallback) ──
    try:
        resp = requests.post(
            f"{base_url}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": caption,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("💬 %s ✅ text: %s", platform_name, item.title[:40])
            return True
        else:
            logger.error(
                "❌ %s sendMessage خطا: %s",
                platform_name,
                data.get("description", ""),
            )
            return False
    except Exception as e:
        logger.error("❌ %s sendMessage exception: %s", platform_name, e)
        return False


# ══════════════════════════════════════════════════════════════════
# کلاس اصلی ارسال
# ══════════════════════════════════════════════════════════════════

class NewsSender:
    """ارسال اخبار به تلگرام و بله"""

    def __init__(self) -> None:
        self._sent_count = 0

    def send(self, item: NewsItem) -> tuple[bool, bool]:
        """ارسال به هر دو پلتفرم — برگرداندن (tg_ok, bale_ok)"""

        tg_ok = _send_to_platform(
            api_base=TELEGRAM_API_BASE,
            token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHANNEL_ID,
            item=item,
            max_cap=TELEGRAM_CAPTION_MAX,
            platform_name="Telegram",
        )

        time.sleep(1)  # تأخیر کوتاه بین دو پلتفرم

        bale_ok = _send_to_platform(
            api_base=BALE_API_BASE,
            token=BALE_BOT_TOKEN,
            chat_id=BALE_CHANNEL_ID,
            item=item,
            max_cap=BALE_CAPTION_MAX,
            platform_name="Bale",
        )

        self._sent_count += 1
        return tg_ok, bale_ok

    def send_batch(
        self,
        items: list[NewsItem],
        max_items: int = 30,
    ) -> list[NewsItem]:
        """ارسال دسته‌ای با تأخیر"""
        sent_items: list[NewsItem] = []

        for item in items[:max_items]:
            tg_ok, bale_ok = self.send(item)
            item.sent_telegram = tg_ok
            item.sent_bale = bale_ok
            if tg_ok or bale_ok:
                sent_items.append(item)
            time.sleep(DELAY_BETWEEN_SENDS)

        logger.info(
            "📤 ارسال کامل شد: %d از %d خبر",
            len(sent_items),
            len(items[:max_items]),
        )
        return sent_items
