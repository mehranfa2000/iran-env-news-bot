# ============================================================
# ابزارهای کمکی - تبدیل تاریخ به شمسی
# ============================================================

import jdatetime
from datetime import datetime, timezone

def to_shamsi(dt=None, fmt="%Y/%m/%d %H:%M"):
    """
    تبدیل تاریخ میلادی به شمسی
    ورودی: datetime object یا None (برای زمان الان)
    خروجی: رشته تاریخ شمسی
    """
    try:
        if dt is None:
            dt = datetime.now()
        elif isinstance(dt, str):
            # تلاش برای تبدیل رشته به datetime
            for fmt_try in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%d"
            ]:
                try:
                    dt = datetime.strptime(dt.strip(), fmt_try)
                    break
                except ValueError:
                    continue
            else:
                # اگر هیچ فرمتی نخورد، زمان الان را برگردان
                dt = datetime.now()

        # حذف timezone برای jdatetime
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)

        jdt = jdatetime.datetime.fromgregorian(datetime=dt)
        return jdt.strftime(fmt)

    except Exception:
        return jdatetime.datetime.now().strftime(fmt)


def now_shamsi(fmt="%Y/%m/%d %H:%M:%S"):
    """زمان الان به شمسی"""
    return jdatetime.datetime.now().strftime(fmt)


def shamsi_date_only(fmt="%Y/%m/%d"):
    """فقط تاریخ امروز به شمسی"""
    return jdatetime.date.today().strftime(fmt)


def weekday_shamsi():
    """نام روز هفته به فارسی"""
    days = ["دوشنبه","سه‌شنبه","چهارشنبه","پنج‌شنبه","جمعه","شنبه","یکشنبه"]
    return days[jdatetime.date.today().weekday()]


def format_shamsi_full():
    """تاریخ کامل فارسی - مثال: شنبه ۱ آذر ۱۴۰۵"""
    months = [
        "فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
        "مهر","آبان","آذر","دی","بهمن","اسفند"
    ]
    today = jdatetime.date.today()
    return f"{weekday_shamsi()} {today.day} {months[today.month-1]} {today.year}"
