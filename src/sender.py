"""
sender.py — v4.0
ارسال اخبار به تلگرام و بله با:
  - تصویر + کپشن HTML زیبا
  - دکمه کلیکی (Inline Keyboard)
  - Emoji های جذاب
  - تاریخ شمسی
  - Fallback به پیام متنی اگر تصویر نداشت
  - Rate limiting و Retry هوشمند
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional
from datetime import timezone

import jdatetime
import requests

from src.config import (
    BALE_API_BASE,
    BALE_BOT_TOKEN,
    BALE_CHANNEL_ID,
    BOT_SIGNATURE,
    DEFAULT_IMAGE_URL,
    DELAY_BETWEEN_PLATFORMS,
    DELAY_BETWEEN_SENDS,
    MAX_CAPTION_LENGTH,
    TELEGRAM_API_BASE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)
from src.filter import FilteredNewsItem
from src.analyzer import AIResult

logger = logging.getLogger("sender")

# ═══════════════════════════════════════════════════════════════
# ۱) نگاشت احساس به emoji
# ═══════════════════════════════════════════════════════════════
SENTIMENT_EMOJI = {
    "منفی":   "🔴",
    "خنثی":   "⚪",
    "مثبت":   "🟢",
    "مختلط":  "🟡",
}

URGENCY_EMOJI = {
    "فوری":        "🚨",
    "۲۴ساعت":     "⚠️",
    "هفته‌جاری":   "📌",
    "عادی":        "ℹ️",
}

SENSITIVITY_EMOJI = {
    "خیلی‌بالا": "🔥",
    "بالا":       "⚡",
    "متوسط":      "📊",
    "پایین":      "📝",
}


# ═══════════════════════════════════════════════════════════════
# ۲) سازنده پیام
# ═══════════════════════════════════════════════════════════════
class MessageBuilder:
    """ساخت پیام HTML جذاب برای تلگرام و بله"""

    @staticmethod
    def shamsi_datetime(dt) -> tuple[str, str]:
        """تبدیل datetime به تاریخ و ساعت شمسی"""
        try:
            if dt.tzinfo is None:
                from datetime import timezone as tz
                dt = dt.replace(tzinfo=tz.utc)
            jdt = jdatetime.datetime.fromgregorian(datetime=dt)
            # نام ماه‌های فارسی
            months = [
                "", "فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
                "مهر","آبان","آذر","دی","بهمن","اسفند"
            ]
            date_str = f"{jdt.day} {months[jdt.month]} {jdt.year}"
            time_str = f"{jdt.hour:02d}:{jdt.minute:02d}"
            return date_str, time_str
        except Exception:
            return "نامشخص", "نامشخص"

    @staticmethod
    def _shorten(text: str, max_len: int = 200) -> str:
        """کوتاه کردن متن با حفظ کلمات"""
        if not text or len(text) <= max_len:
            return text
        truncated = text[:max_len].rsplit(" ", 1)[0]
        return truncated + "…"

    def build_caption(
        self,
        item: FilteredNewsItem,
        ai_result: Optional[AIResult] = None,
    ) -> str:
        """
        ساخت کپشن HTML زیبا برای ارسال با تصویر
        حداکثر MAX_CAPTION_LENGTH کاراکتر
        """
        date_str, time_str = self.shamsi_datetime(item.published_dt)

        # ── هدر ───────────────────────────────────────────────
        lines: list[str] = []

        # وضعیت بحرانی
        if item.critical:
            lines.append("🚨 <b>خبر بحرانی محیط‌زیست</b> 🚨")
            lines.append("")

        # دسته
        lines.append(
            f"{item.category.emoji} <b>{item.category.name}</b>"
        )
        lines.append("")

        # عنوان
        lines.append(f"📰 <b>{item.title}</b>")
        lines.append("")

        # خلاصه AI یا خلاصه اصلی
        if ai_result and ai_result.ai_summary:
            lines.append(f"🤖 <i>{self._shorten(ai_result.ai_summary, 180)}</i>")
        elif item.summary:
            lines.append(f"📝 {self._shorten(item.summary, 180)}")
        lines.append("")

        # تحلیل بحرانی (فقط اگر تحلیل کامل داشت)
        if ai_result and ai_result.pr_analysis:
            pr = ai_result.pr_analysis
            sens_e = SENSITIVITY_EMOJI.get(pr.sensitivity, "📊")
            sent_e = SENTIMENT_EMOJI.get(pr.sentiment, "⚪")
            urg_e  = URGENCY_EMOJI.get(pr.urgency, "ℹ️")

            lines.append("─" * 20)
            lines.append(
                f"{sens_e} <b>حساسیت:</b> {pr.sensitivity}  "
                f"{sent_e} <b>احساس:</b> {pr.sentiment}  "
                f"{urg_e} <b>فوریت:</b> {pr.urgency}"
            )
            if pr.action:
                lines.append(f"✅ <b>اقدام:</b> {self._shorten(pr.action, 120)}")
            lines.append("─" * 20)
            lines.append("")

        # اطلاعات منبع
        lines.append(
            f"🏛 <b>منبع:</b> {item.source}   "
            f"📅 {date_str}   🕐 {time_str}"
        )
        lines.append("")

        # امضا
        lines.append(BOT_SIGNATURE)

        caption = "\n".join(lines)

        # اگر از حد مجاز بیشتر شد، کوتاه کن
        if len(caption) > MAX_CAPTION_LENGTH:
            # نسخه ساده
            caption = self._build_simple_caption(item, ai_result, date_str, time_str)

        return caption

    def _build_simple_caption(
        self,
        item: FilteredNewsItem,
        ai_result: Optional[AIResult],
        date_str: str,
        time_str: str,
    ) -> str:
        """نسخه کوتاه‌شده کپشن برای تصاویر با متن محدود"""
        ai_sum = ""
        if ai_result and ai_result.ai_summary:
            ai_sum = f"\n🤖 <i>{self._shorten(ai_result.ai_summary, 120)}</i>"

        critical_tag = "🚨 " if item.critical else ""

        return (
            f"{critical_tag}{item.category.emoji} <b>{item.category.name}</b>\n\n"
            f"📰 <b>{self._shorten(item.title, 150)}</b>"
            f"{ai_sum}\n\n"
            f"🏛 {item.source} | 📅 {date_str} | 🕐 {time_str}\n\n"
            f"{BOT_SIGNATURE}"
        )

    @staticmethod
    def build_inline_keyboard(link: str) -> dict:
        """دکمه کلیکی 'مطالعه خبر' برای تلگرام"""
        return {
            "inline_keyboard": [[
                {
                    "text": "📖 مطالعه کامل خبر",
                    "url": link,
                }
            ]]
        }

    @staticmethod
    def build_bale_keyboard(link: str) -> dict:
        """دکمه کلیکی برای بله (فرمت مشابه تلگرام)"""
        return {
            "inline_keyboard": [[
                {
                    "text": "📖 مطالعه خبر",
                    "url": link,
                }
            ]]
        }


# ═══════════════════════════════════════════════════════════════
# ۳) کلاس ارسال‌کننده
# ═══════════════════════════════════════════════════════════════
@dataclass
class SendResult:
    uid: str
    telegram_ok: bool = False
    bale_ok: bool     = False
    error: str        = ""


class NewsSender:
    """ارسال‌کننده اخبار به تلگرام و بله"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.builder = MessageBuilder()
        self._tg_base  = TELEGRAM_API_BASE
        self._bale_base = BALE_API_BASE

    # ── ارسال دسته‌ای ──────────────────────────────────────────

    def send_batch(
        self,
        items: list[FilteredNewsItem],
        ai_results: dict[str, AIResult],
    ) -> list[SendResult]:
        """
        همه خبرهای جدید را یکی‌یکی ارسال می‌کند.
        تأخیر بین ارسال‌ها برای جلوگیری از Rate Limit.
        """
        results: list[SendResult] = []
        total = len(items)

        logger.info("📤 شروع ارسال %d خبر به تلگرام و بله", total)

        for idx, item in enumerate(items, 1):
            ai_result = ai_results.get(item.uid)
            logger.info(
                "📨 ارسال %d/%d: %s", idx, total, item.title[:50]
            )

            result = self._send_one(item, ai_result)
            results.append(result)

            if idx < total:
                time.sleep(DELAY_BETWEEN_SENDS)

        ok_tg   = sum(1 for r in results if r.telegram_ok)
        ok_bale = sum(1 for r in results if r.bale_ok)
        logger.info(
            "✅ ارسال کامل: تلگرام %d/%d | بله %d/%d",
            ok_tg, total, ok_bale, total,
        )
        return results

    def _send_one(
        self, item: FilteredNewsItem, ai_result: Optional[AIResult]
    ) -> SendResult:
        """یک خبر را به هر دو پلتفرم ارسال می‌کند."""
        result = SendResult(uid=item.uid)
        caption = self.builder.build_caption(item, ai_result)

        # تلگرام
        result.telegram_ok = self._send_telegram(item, caption)

        time.sleep(DELAY_BETWEEN_PLATFORMS)

        # بله
        result.bale_ok = self._send_bale(item, caption)

        return result

    # ── تلگرام ────────────────────────────────────────────────

    def _send_telegram(
        self, item: FilteredNewsItem, caption: str
    ) -> bool:
        """ارسال به تلگرام: اول با عکس، اگر نشد متن ساده"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
            logger.warning("⚠️ تلگرام: توکن یا کانال تنظیم نشده")
            return False

        keyboard = self.builder.build_inline_keyboard(item.link)

        # تلاش با عکس
        image_url = item.image_url or DEFAULT_IMAGE_URL
        ok = self._tg_send_photo(image_url, caption, keyboard)
        if ok:
            return True

        # fallback: متن ساده با لینک
        logger.info("📝 Fallback به پیام متنی برای [%s]", item.uid[:8])
        return self._tg_send_text(caption, keyboard)

    def _tg_send_photo(
        self, image_url: str, caption: str, keyboard: dict
    ) -> bool:
        """sendPhoto به تلگرام"""
        return self._post_with_retry(
            f"{self._tg_base}/sendPhoto",
            {
                "chat_id":              TELEGRAM_CHANNEL_ID,
                "photo":                image_url,
                "caption":              caption,
                "parse_mode":           "HTML",
                "reply_markup":         keyboard,
                "disable_notification": False,
            },
        )

    def _tg_send_text(self, text: str, keyboard: dict) -> bool:
        """sendMessage به تلگرام (بدون عکس)"""
        return self._post_with_retry(
            f"{self._tg_base}/sendMessage",
            {
                "chat_id":    TELEGRAM_CHANNEL_ID,
                "text":       text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": False,
            },
        )

    # ── بله ───────────────────────────────────────────────────

    def _send_bale(
        self, item: FilteredNewsItem, caption: str
    ) -> bool:
        """ارسال به بله: اول با عکس، اگر نشد متن ساده"""
        if not BALE_BOT_TOKEN or not BALE_CHANNEL_ID:
            logger.warning("⚠️ بله: توکن یا کانال تنظیم نشده")
            return False

        keyboard = self.builder.build_bale_keyboard(item.link)

        # تلاش با عکس
        image_url = item.image_url or DEFAULT_IMAGE_URL
        ok = self._bale_send_photo(image_url, caption, keyboard)
        if ok:
            return True

        # fallback: متن ساده
        logger.info("📝 Fallback بله به پیام متنی برای [%s]", item.uid[:8])
        return self._bale_send_text(caption, keyboard)

    def _bale_send_photo(
        self, image_url: str, caption: str, keyboard: dict
    ) -> bool:
        return self._post_with_retry(
            f"{self._bale_base}/sendPhoto",
            {
                "chat_id":    BALE_CHANNEL_ID,
                "photo":      image_url,
                "caption":    caption,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
        )

    def _bale_send_text(self, text: str, keyboard: dict) -> bool:
        return self._post_with_retry(
            f"{self._bale_base}/sendMessage",
            {
                "chat_id":    BALE_CHANNEL_ID,
                "text":       text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
        )

    # ── HTTP با Retry ──────────────────────────────────────────

    def _post_with_retry(
        self,
        url: str,
        payload: dict,
        max_retries: int = 3,
    ) -> bool:
        """POST با retry و backoff نمایی"""
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=15)
                data = resp.json()

                if resp.status_code == 200 and data.get("ok"):
                    return True

                # Rate limit تلگرام/بله
                if resp.status_code == 429:
                    retry_after = data.get("parameters", {}).get(
                        "retry_after", 10
                    )
                    logger.warning(
                        "⏳ Rate limit — %d ثانیه صبر (تلاش %d/%d)",
                        retry_after, attempt, max_retries,
                    )
                    time.sleep(retry_after + 1)
                    continue

                # خطای تصویر نامعتبر
                desc = data.get("description", "")
                if "wrong file identifier" in desc or "Bad Request" in desc:
                    logger.debug("🖼 تصویر نامعتبر: %s", desc)
                    return False  # به fallback برو

                logger.warning(
                    "⚠️ API پاسخ ناموفق (تلاش %d/%d): %s",
                    attempt, max_retries, desc,
                )

            except requests.Timeout:
                logger.warning("⏰ Timeout (تلاش %d/%d)", attempt, max_retries)
            except requests.ConnectionError as exc:
                logger.warning("🔌 اتصال قطع شد (تلاش %d/%d): %s", attempt, max_retries, exc)
            except Exception as exc:
                logger.error("❌ خطای غیرمنتظره: %s", exc)
                return False

            if attempt < max_retries:
                wait = 2 ** attempt
                time.sleep(wait)

        return False


# ── تابع سطح بالا ─────────────────────────────────────────────
def send_news(
    items: list[FilteredNewsItem],
    ai_results: dict[str, AIResult],
) -> list[SendResult]:
    return NewsSender().send_batch(items, ai_results)
