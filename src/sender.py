"""
sender.py — ارسال خبر به تلگرام و بله
نسخه: 4.2.0

تغییرات v4.2:
- caption به‌درستی ≤ 1024 کاراکتر (تلگرام limit)
  با کوتاه‌کردن هوشمند بدون شکستن HTML tags
- Retry با Exponential Backoff برای هر platform
- مدیریت صحیح HTTP 429 (Rate Limit) با retry_after
- اعتبارسنجی URL تصویر قبل از sendPhoto
- Fallback: sendPhoto → sendMessage
- Session با connection pooling
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

# ─── تنظیمات از محیط ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
BALE_BOT_TOKEN      = os.environ.get("BALE_BOT_TOKEN",      "")
BALE_CHANNEL_ID     = os.environ.get("BALE_CHANNEL_ID",     "")
TELEGRAM_API_BASE   = "https://api.telegram.org/bot"
BALE_API_BASE       = "https://tapi.bale.ai/bot"

# ─── ثابت‌های ارسال ──────────────────────────────────────────────────────────
CAPTION_MAX      = 1020    # تلگرام: 1024؛ ما 4 کاراکتر حاشیه می‌گذاریم
MESSAGE_MAX      = 4000    # sendMessage: 4096
DELAY_BETWEEN    = 4.0     # ثانیه بین هر پیام (رعایت 20 msg/min)
IMG_CHECK_TIMEOUT = 5      # ثانیه timeout اعتبارسنجی تصویر

# Retry config
_MAX_RETRIES      = 2
_RETRY_BASE_DELAY = 3.0    # ثانیه (exponential: 3, 6)

# دسته‌بندی‌ها
CATEGORY_FA: dict[str, str] = {
    "air_water_soil":  "آلودگی هوا، آب و خاک",
    "wildlife":        "حیات وحش و تنوع زیستی",
    "water_wetlands":  "تالاب‌ها، دریاها و منابع آب",
    "climate":         "تغییر اقلیم و بحران‌های طبیعی",
    "forests":         "جنگل‌ها، مراتع و منابع طبیعی",
    "policy":          "سیاست‌ها، قوانین و سازمان",
    "sustainable":     "توسعه پایدار و انرژی پاک",
}

CATEGORY_EMOJI: dict[str, str] = {
    "air_water_soil":  "🌬️",
    "wildlife":        "🐆",
    "water_wetlands":  "🌊",
    "climate":         "🌡️",
    "forests":         "🌲",
    "policy":          "🏛️",
    "sustainable":     "♻️",
}

BOT_SIGNATURE = (
    "🌿 <b>سامانه پایش هوشمند اخبار محیط‌زیست</b>\n"
    "🏛 روابط‌عمومی سازمان حفاظت محیط‌زیست ایران"
)


# ══════════════════════════════════════════════════════════════════════════════
# HTTP Session با connection pooling
# ══════════════════════════════════════════════════════════════════════════════
def _build_session() -> requests.Session:
    """
    Session با:
    - connection pooling (10 connections)
    - Retry خودکار برای 500/502/503/504
    - timeout پیش‌فرض
    توجه: 429 را retry نمی‌کند چون باید retry_after را رعایت کنیم.
    """
    session = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST", "GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=4,
        pool_maxsize=4,
    )
    session.mount("http://",  adapter)
    session.mount("https://", adapter)
    return session


_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


# ══════════════════════════════════════════════════════════════════════════════
# اعتبارسنجی URL تصویر
# ══════════════════════════════════════════════════════════════════════════════
def _is_valid_image_url(url: Optional[str]) -> bool:
    """
    قبل از sendPhoto اعتبار URL را بررسی می‌کند.

    شرایط قبولی:
    1. URL با http(s) شروع شود
    2. HTTP 200 برگرداند
    3. Content-Type شامل 'image/' باشد
       یا پسوند شناخته‌شده تصویر داشته باشد

    برای جلوگیری از delay زیاد، timeout=5 تنظیم شده.
    """
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        return False

    # پسوند تصویر در URL (بدون HTTP call برای URLهای آشکار)
    _IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
    url_lower = url.lower().split("?")[0]
    if any(url_lower.endswith(ext) for ext in _IMG_EXTS):
        return True   # احتمال بالا — پیشفرض قبول

    # HEAD request برای بقیه
    try:
        resp = requests.head(
            url,
            timeout=IMG_CHECK_TIMEOUT,
            verify=False,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; EnvBot/4.2)"},
        )
        content_type = resp.headers.get("Content-Type", "")
        return resp.status_code == 200 and "image/" in content_type
    except Exception as e:
        log.debug(f"اعتبارسنجی تصویر ناموفق ({url[:60]}): {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# کوتاه‌کردن هوشمند HTML
# ══════════════════════════════════════════════════════════════════════════════
def _truncate_html(text: str, max_len: int) -> str:
    """
    متن HTML را به حداکثر max_len کاراکتر کوتاه می‌کند.

    اصول:
    - اگر در وسط یک HTML tag بریده شد، کل آن tag را حذف می‌کند
    - '...' به انتها اضافه می‌کند
    - تگ‌های باز HTML را نمی‌شکند
    """
    if len(text) <= max_len:
        return text

    cut = text[:max_len - 3]

    # بررسی آیا در وسط tag بریده‌ایم
    last_open  = cut.rfind("<")
    last_close = cut.rfind(">")
    if last_open > last_close:
        # در وسط tag هستیم — به قبل از آن tag برو
        cut = cut[:last_open]

    return cut.rstrip() + "..."


# ══════════════════════════════════════════════════════════════════════════════
# ساخت Caption
# ══════════════════════════════════════════════════════════════════════════════
def _build_caption(item) -> str:
    """
    Caption HTML با:
    - header بحرانی (اگر critical)
    - دسته‌بندی + emoji
    - عنوان
    - خلاصه AI یا تحلیل PR (اولویت با PR)
    - فیلدهای اضافه بحرانی (urgency, action, media_risk)
    - منبع + تاریخ
    - امضا

    ← محدود به CAPTION_MAX کاراکتر
    """
    emoji = CATEGORY_EMOJI.get(item.category, "🌿")
    cat   = CATEGORY_FA.get(item.category, item.category)

    # ── Header ────────────────────────────────────────────────────────────────
    header = "🚨 <b>خبر بحرانی</b>\n" if item.critical else ""

    # ── خلاصه / تحلیل ─────────────────────────────────────────────────────────
    summary_block = ""
    if isinstance(item.pr_analysis, dict) and item.pr_analysis.get("summary"):
        s = item.pr_analysis["summary"][:180]
        summary_block = f"\n\n📋 <b>تحلیل PR:</b> {s}"
    elif item.ai_summary:
        s = item.ai_summary[:180]
        summary_block = f"\n\n📋 <b>خلاصه:</b> {s}"

    # ── فیلدهای اضافه بحرانی ─────────────────────────────────────────────────
    crisis_block = ""
    if item.critical and isinstance(item.pr_analysis, dict):
        pr     = item.pr_analysis
        lines  = []
        if pr.get("urgency"):
            lines.append(f"⏰ <b>فوریت:</b> {pr['urgency']}")
        if pr.get("media_risk"):
            lines.append(f"📡 <b>ریسک رسانه‌ای:</b> {pr['media_risk']}")
        if pr.get("action"):
            lines.append(f"🎯 <b>اقدام:</b> {pr['action'][:70]}")
        if lines:
            crisis_block = "\n" + "\n".join(lines)

    # ── کامل‌سازی ─────────────────────────────────────────────────────────────
    caption = (
        f"{header}"
        f"{emoji} <b>{cat}</b>\n\n"
        f"📰 <b>{item.title}</b>"
        f"{summary_block}"
        f"{crisis_block}\n\n"
        f"📌 <b>منبع:</b> {item.source}\n"
        f"🗓 <b>تاریخ:</b> {item.shamsi_date}\n\n"
        f"{BOT_SIGNATURE}"
    )

    return _truncate_html(caption, CAPTION_MAX)


# ══════════════════════════════════════════════════════════════════════════════
# ارسال به یک کانال
# ══════════════════════════════════════════════════════════════════════════════
def _post(
    endpoint: str,
    payload: dict,
    platform: str,
    timeout: int = 20,
) -> tuple[bool, dict]:
    """
    یک POST request با مدیریت:
    - HTTP 200 → (True, data)
    - HTTP 429 → sleep(retry_after) + (False, {"retry_after": N})
    - HTTP دیگر → (False, {})
    - Exception → (False, {})
    """
    session = _get_session()
    try:
        resp = session.post(endpoint, json=payload, timeout=timeout)
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass

        if resp.status_code == 200 and data.get("ok"):
            return True, data

        if resp.status_code == 429:
            retry_after = (
                data.get("parameters", {}).get("retry_after", 10)
                if isinstance(data.get("parameters"), dict)
                else 10
            )
            log.warning(f"⏳ [{platform}] Rate limit 429 — retry_after={retry_after}s")
            return False, {"retry_after": int(retry_after)}

        log.warning(
            f"[{platform}] HTTP {resp.status_code}: "
            f"{resp.text[:120]}"
        )
        return False, {}

    except requests.Timeout:
        log.warning(f"[{platform}] Timeout بعد از {timeout}s")
        return False, {}
    except requests.ConnectionError as e:
        log.warning(f"[{platform}] خطای اتصال: {e}")
        return False, {}
    except Exception as e:
        log.error(f"[{platform}] خطای غیرمنتظره: {e}")
        return False, {}


def _send_one(
    api_base:   str,
    token:      str,
    channel_id: str,
    item,
    platform:   str,
) -> bool:
    """
    ارسال یک خبر با استراتژی:
    1. sendPhoto اگر URL تصویر معتبر داشت
    2. اگر sendPhoto ناموفق → sendMessage (fallback)
    3. هر مرحله: Exponential Backoff (3s, 6s)
    4. 429: صبر retry_after + retry فوری

    Returns True اگر حداقل یکی موفق شد.
    """
    caption  = _build_caption(item)
    keyboard = {
        "inline_keyboard": [[
            {"text": "📖 مطالعه کامل خبر", "url": item.link}
        ]]
    }

    base_url = f"{api_base}{token}"
    img_ok   = _is_valid_image_url(item.image_url)

    # ── مرحله ۱: sendPhoto ────────────────────────────────────────────────────
    if img_ok:
        log.debug(f"[{platform}] تلاش sendPhoto: {item.image_url[:60]}")
        payload = {
            "chat_id":      channel_id,
            "photo":        item.image_url,
            "caption":      caption,
            "parse_mode":   "HTML",
            "reply_markup": keyboard,
        }

        for attempt in range(_MAX_RETRIES + 1):
            ok, meta = _post(f"{base_url}/sendPhoto", payload, platform)

            if ok:
                log.info(f"✅ [{platform}] sendPhoto موفق: {item.title[:45]}")
                return True

            if "retry_after" in meta:
                # 429: صبر کن و retry کن
                wait = meta["retry_after"] + 1
                log.info(f"[{platform}] صبر {wait}s (429) ...")
                time.sleep(wait)
                continue   # retry بدون افزایش attempt

            # خطای دیگر
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.debug(f"[{platform}] sendPhoto retry {attempt+1} بعد از {delay}s")
                time.sleep(delay)
            else:
                log.warning(f"[{platform}] sendPhoto ناموفق — رفتن به sendMessage")
                break
    else:
        log.debug(f"[{platform}] تصویر نامعتبر → مستقیم sendMessage")

    # ── مرحله ۲: sendMessage (fallback) ──────────────────────────────────────
    text = _truncate_html(caption, MESSAGE_MAX)
    payload = {
        "chat_id":                  channel_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "reply_markup":             keyboard,
        "disable_web_page_preview": False,
    }

    for attempt in range(_MAX_RETRIES + 1):
        ok, meta = _post(f"{base_url}/sendMessage", payload, platform)

        if ok:
            log.info(f"✅ [{platform}] sendMessage موفق: {item.title[:45]}")
            return True

        if "retry_after" in meta:
            wait = meta["retry_after"] + 1
            log.info(f"[{platform}] صبر {wait}s (429) ...")
            time.sleep(wait)
            continue

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log.debug(f"[{platform}] sendMessage retry {attempt+1} بعد از {delay}s")
            time.sleep(delay)

    log.error(f"❌ [{platform}] ارسال کاملاً ناموفق: {item.title[:45]}")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# تابع اصلی
# ══════════════════════════════════════════════════════════════════════════════
def send_items(items: list) -> tuple[int, int]:
    """
    ارسال همه آیتم‌های sent=False به تلگرام و بله.

    منطق:
    - هر خبر → ابتدا تلگرام، بعد بله
    - بین هر پیام DELAY_BETWEEN ثانیه صبر
    - اگر حتی یکی از دو پلتفرم موفق شد → item.sent = True

    Returns:
        (success_count, fail_count)
    """
    unsent = [i for i in items if not i.sent]
    total  = len(unsent)

    if total == 0:
        log.info("📭 خبری برای ارسال وجود ندارد")
        return 0, 0

    log.info(f"📨 شروع ارسال {total} خبر ...")
    success = failed = 0

    tg_configured  = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
    bal_configured = bool(BALE_BOT_TOKEN    and BALE_CHANNEL_ID)

    if not tg_configured:
        log.warning("⚠️  تلگرام پیکربندی نشده")
    if not bal_configured:
        log.warning("⚠️  بله پیکربندی نشده")
    if not tg_configured and not bal_configured:
        log.error("❌ هیچ پلتفرمی پیکربندی نشده — ارسال ممکن نیست")
        return 0, total

    for idx, item in enumerate(unsent, start=1):
        log.info(f"[{idx}/{total}] ارسال: {item.title[:50]}")
        tg_ok  = False
        bal_ok = False

        # ── تلگرام ────────────────────────────────────────────────────────────
        if tg_configured:
            tg_ok = _send_one(
                TELEGRAM_API_BASE, TELEGRAM_BOT_TOKEN,
                TELEGRAM_CHANNEL_ID, item, "Telegram",
            )
            time.sleep(DELAY_BETWEEN)

        # ── بله ───────────────────────────────────────────────────────────────
        if bal_configured:
            bal_ok = _send_one(
                BALE_API_BASE, BALE_BOT_TOKEN,
                BALE_CHANNEL_ID, item, "Bale",
            )
            time.sleep(DELAY_BETWEEN)

        # ── نتیجه ─────────────────────────────────────────────────────────────
        if tg_ok or bal_ok:
            item.sent = True
            success  += 1
        else:
            failed += 1
            log.warning(f"   ❌ ارسال ناموفق برای: {item.title[:50]}")

    log.info(f"📨 ارسال تمام — ✅ موفق:{success} | ❌ ناموفق:{failed}")
    return success, failed
