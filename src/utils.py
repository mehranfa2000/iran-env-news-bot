# ============================================================
#  src/utils.py — ابزارهای کمکی (تاریخ شمسی و غیره)
# ============================================================

from datetime import datetime, timezone
import jdatetime


def gregorian_to_shamsi(dt: datetime | None = None) -> str:
    """
    تبدیل تاریخ میلادی به شمسی (فارسی)

    Args:
        dt: شیء datetime میلادی (اگر None بود، زمان حالا)

    Returns:
        رشته تاریخ شمسی مثل «۱۴۰۵/۰۹/۰۱»
    """
    if dt is None:
        dt = datetime.now()

    # اگر timezone-aware بود، به naive تبدیل کن
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)

    try:
        jdt = jdatetime.datetime.fromgregorian(datetime=dt)
        # فرمت: ۱۴۰۵/۰۹/۰۱
        return jdt.strftime("%Y/%m/%d")
    except Exception:
        return dt.strftime("%Y/%m/%d")


def parse_rss_date(date_str: str) -> str:
    """
    تبدیل رشته تاریخ RSS به تاریخ شمسی

    Args:
        date_str: رشته تاریخ از RSS (مثل 'Mon, 01 Jan 2024 ...')

    Returns:
        تاریخ شمسی یا تاریخ امروز در صورت خطا
    """
    if not date_str:
        return gregorian_to_shamsi()

    # فرمت‌های رایج RSS
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d %b %Y %H:%M:%S %z",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return gregorian_to_shamsi(dt)
        except ValueError:
            continue

    # اگر هیچ فرمتی کار نکرد، تاریخ امروز
    return gregorian_to_shamsi()


def now_shamsi() -> str:
    """تاریخ شمسی امروز"""
    return gregorian_to_shamsi(datetime.now())


def now_utc_iso() -> str:
    """زمان حالا به فرمت ISO 8601 با UTC"""
    return datetime.now(timezone.utc).isoformat()
