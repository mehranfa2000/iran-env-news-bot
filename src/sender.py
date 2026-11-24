# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  src/sender.py  ·  v4.1  ·  ارسال به تلگرام و بله                         ║
# ║  sendPhoto + caption HTML + inline keyboard · fallback text · Shamsi date   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from src.agent  import NewsItem
from src.config import (
    BALE_API_BASE,
    BALE_BOT_TOKEN,
    BALE_CHANNEL_ID,
    BOT_SIGNATURE,
    CATEGORIES,
    DELAY_BETWEEN_SENDS,
    MAX_CAPTION_LENGTH,
    MAX_RETRIES_SEND,
    TELEGRAM_API_BASE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  ۱. ساخت متن پیام
# ══════════════════════════════════════════════════════════════════════════════

def _build_caption(item: NewsItem) -> str:
    """
    ساخت caption HTML برای پیام تلگرام/بله.
    شامل: دسته‌بندی، عنوان، خلاصه AI، تحلیل PR (بحرانی)، منبع، تاریخ شمسی.
    حداکثر MAX_CAPTION_LENGTH کاراکتر.
    """
    cat = CATEGORIES.get(item.category, {})
    emoji = cat.get("emoji", "🌿")
    label = cat.get("label", item.category)

    lines: list[str] = []

    # ── سربرگ ────────────────────────────────────────────────────────────────
    if item.critical:
        lines.append(f"🚨 <b>خبر بحرانی</b>")
    lines.append(f"{emoji} <b>{label}</b>")
    lines.append("")

    # ── عنوان ────────────────────────────────────────────────────────────────
    lines.append(f"📰 <b>{item.title}</b>")
    lines.append("")

    # ── خلاصه AI یا خلاصه اولیه ──────────────────────────────────────────────
    if item.ai_summary:
        lines.append(f"🤖 <i>{item.ai_summary}</i>")
    elif item.summary:
        lines.append(f"📄 {item.summary[:300]}")
    lines.append("")

    # ── تحلیل PR برای اخبار بحرانی ───────────────────────────────────────────
    if item.critical and item.pr_analysis:
        pr = item.pr_analysis
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("📊 <b>تحلیل روابط‌عمومی</b>")

        if pr.get("sensitivity"):
            lines.append(f"🔴 حساسیت: <b>{pr['sensitivity']}</b>")
        if pr.get("urgency"):
            lines.append(f"⏰ فوریت: <b>{pr['urgency']}</b>")
        if pr.get("media_risk"):
            lines.append(f"📡 خطر رسانه‌ای: <b>{pr['media_risk']}</b>")
        if pr.get("action"):
            lines.append(f"⚡ اقدام: {pr['action'][:150]}")
        lines.append("")

    # ── منبع و تاریخ ─────────────────────────────────────────────────────────
    lines.append(f"📡 <b>منبع:</b> {item.source}")
    lines.append(f"🗓 <b>تاریخ:</b> {item.shamsi_date}")

    # ── امضا ─────────────────────────────────────────────────────────────────
    lines.append(BOT_SIGNATURE)

    caption = "\n".join(lines)

    # برش اگر از حد مجاز بیشتر شد
    if len(caption) > MAX_CAPTION_LENGTH:
        caption = caption[:MAX_CAPTION_LENGTH - 10] + "\n..."

    return caption


def _build_inline_keyboard(item: NewsItem) -> dict:
    """ساخت inline keyboard با دکمه لینک خبر."""
    return {
        "inline_keyboard": [[
            {
                "text": "📖 مطالعه کامل خبر",
                "url": item.link,
            }
        ]]
    }

# ══════════════════════════════════════════════════════════════════════════════
#  ۲. ارسال به یک پلتفرم
# ══════════════════════════════════════════════════════════════════════════════

def _send_to_platform(
    api_base:   str,
    bot_token:  str,
    channel_id: str,
    item:       NewsItem,
    platform:   str,
) -> bool:
    """
    ارسال خبر به یک پلتفرم (تلگرام یا بله).
    الویت: sendPhoto → اگر شکست خورد → sendMessage
    """
    caption  = _build_caption(item)
    keyboard = _build_inline_keyboard(item)

    base_url = f"{api_base}{bot_token}"

    # ── تلاش اول: sendPhoto ──────────────────────────────────────────────────
    if item.image_url:
        success = _send_photo(
            base_url   = base_url,
            channel_id = channel_id,
            image_url  = item.image_url,
            caption    = caption,
            keyboard   = keyboard,
            platform   = platform,
        )
        if success:
            return True
        logger.warning(
            "⚠️ %s — sendPhoto شکست خورد، fallback به sendMessage",
            platform
        )

    # ── fallback: sendMessage ────────────────────────────────────────────────
    return _send_message(
        base_url   = base_url,
        channel_id = channel_id,
        text       = caption,
        keyboard   = keyboard,
        platform   = platform,
    )


def _send_photo(
    base_url:   str,
    channel_id: str,
    image_url:  str,
    caption:    str,
    keyboard:   dict,
    platform:   str,
) -> bool:
    """ارسال پیام با عکس."""
    url = f"{base_url}/sendPhoto"
    payload = {
        "chat_id":             channel_id,
        "photo":               image_url,
        "caption":             caption,
        "parse_mode":          "HTML",
        "reply_markup":        keyboard,
        "disable_notification": False,
    }

    for attempt in range(1, MAX_RETRIES_SEND + 1):
        try:
            resp = requests.post(url, json=payload, timeout=20)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.debug("✅ %s sendPhoto موفق", platform)
                    return True
                else:
                    err = data.get("description", "نامعلوم")
                    logger.warning("⚠️ %s sendPhoto — %s", platform, err)
                    # اگر مشکل از تصویر است → retry نکن
                    if any(x in err.lower() for x in ["photo", "image", "url", "wrong"]):
                        return False
                    return False

            elif resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 10))
                logger.warning("⏳ %s rate limit — %ds صبر", platform, retry_after)
                time.sleep(retry_after)
                continue

            else:
                logger.warning("⚠️ %s sendPhoto HTTP %d", platform, resp.status_code)
                if attempt < MAX_RETRIES_SEND:
                    time.sleep(3 * attempt)

        except requests.exceptions.Timeout:
            logger.warning("⏱ %s sendPhoto timeout (تلاش %d)", platform, attempt)
            if attempt < MAX_RETRIES_SEND:
                time.sleep(3)
        except Exception as exc:
            logger.error("❌ %s sendPhoto خطا: %s", platform, exc)
            if attempt < MAX_RETRIES_SEND:
                time.sleep(3)

    return False


def _send_message(
    base_url:   str,
    channel_id: str,
    text:       str,
    keyboard:   dict,
    platform:   str,
) -> bool:
    """ارسال پیام متنی (بدون عکس)."""
    url = f"{base_url}/sendMessage"
    payload = {
        "chat_id":                  channel_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "reply_markup":             keyboard,
        "disable_web_page_preview": False,
        "disable_notification":     False,
    }

    for attempt in range(1, MAX_RETRIES_SEND + 1):
        try:
            resp = requests.post(url, json=payload, timeout=20)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.debug("✅ %s sendMessage موفق", platform)
                    return True
                else:
                    err = data.get("description", "نامعلوم")
                    logger.warning("⚠️ %s sendMessage — %s", platform, err)
                    return False

            elif resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 10))
                logger.warning("⏳ %s rate limit — %ds صبر", platform, retry_after)
                time.sleep(retry_after)
                continue

            else:
                logger.warning("⚠️ %s sendMessage HTTP %d", platform, resp.status_code)
                if attempt < MAX_RETRIES_SEND:
                    time.sleep(3 * attempt)

        except requests.exceptions.Timeout:
            logger.warning("⏱ %s sendMessage timeout (تلاش %d)", platform, attempt)
            if attempt < MAX_RETRIES_SEND:
                time.sleep(3)
        except Exception as exc:
            logger.error("❌ %s sendMessage خطا: %s", platform, exc)
            if attempt < MAX_RETRIES_SEND:
                time.sleep(3)

    return False

# ══════════════════════════════════════════════════════════════════════════════
#  ۳. ارسال به هر دو کانال
# ══════════════════════════════════════════════════════════════════════════════

def send_news_item(item: NewsItem) -> bool:
    """
    ارسال یک خبر به هر دو کانال (تلگرام + بله).
    اگر حداقل یکی موفق شد → True
    تاخیر DELAY_BETWEEN_SENDS ثانیه بین ارسال‌ها.
    """
    logger.info("📤 ارسال: %s", item.title[:50])

    results: list[bool] = []

    # ── تلگرام ───────────────────────────────────────────────────────────────
    tg_ok = _send_to_platform(
        api_base   = TELEGRAM_API_BASE,
        bot_token  = TELEGRAM_BOT_TOKEN,
        channel_id = TELEGRAM_CHANNEL_ID,
        item       = item,
        platform   = "Telegram",
    )
    results.append(tg_ok)
    logger.info(
        "%s Telegram: %s",
        "✅" if tg_ok else "❌",
        item.title[:40]
    )

    # تاخیر بین دو پلتفرم
    time.sleep(DELAY_BETWEEN_SENDS)

    # ── بله ──────────────────────────────────────────────────────────────────
    bale_ok = _send_to_platform(
        api_base   = BALE_API_BASE,
        bot_token  = BALE_BOT_TOKEN,
        channel_id = BALE_CHANNEL_ID,
        item       = item,
        platform   = "Bale",
    )
    results.append(bale_ok)
    logger.info(
        "%s Bale: %s",
        "✅" if bale_ok else "❌",
        item.title[:40]
    )

    # تاخیر قبل از خبر بعدی
    time.sleep(DELAY_BETWEEN_SENDS)

    any_success = any(results)
    return any_success
