"""
ranking.py — امتیازدهی و انتخاب بهترین خبرها (مرحله ۲ / آیتم ۳)
نسخه: 4.5.0

امتیاز نهایی (۰–۱۰۰) ترکیب وزنی چهار مؤلفه است:
  relevance  امتیاز کلیدواژه‌ای فیلتر / آستانهٔ بحرانی (سقف ۱)
  freshness  0.5 ^ (سن‌به‌ساعت / نیمه‌عمر)
  source     اعتبار منبع (SOURCE_WEIGHTS یا پیش‌فرض اختصاصی/عمومی)
  coverage   پوشش چندمنبعی: ۰٫۳۳ به‌ازای هر منبع اضافه (سقف ۱)
+ پاداش ثابت برای خبر بحرانی.

وزن‌ها خودکار نرمال می‌شوند (جمعشان لازم نیست ۱ باشد).
«score» ذخیره‌شده در NewsItem همان امتیاز کلیدواژه‌ای می‌ماند (سازگاری با داشبورد)؛
rank فقط برای انتخاب/ترتیب ارسال استفاده می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.config import (
    CRITICAL_SCORE_THRESHOLD,
    RANK_CRITICAL_BONUS,
    RANK_DEFAULT_DEDICATED,
    RANK_DEFAULT_GENERAL,
    RANK_HALF_LIFE_HOURS,
    RANK_W_COVERAGE,
    RANK_W_FRESHNESS,
    RANK_W_RELEVANCE,
    RANK_W_SOURCE,
    SOURCE_WEIGHTS,
)


@dataclass(frozen=True)
class RankedItem:
    raw: Any
    result: Any
    rank: float
    parts: Mapping[str, float] = field(default_factory=dict)

    def __iter__(self):
        """باز کردن به (raw, result) مثل خروجی filter_articles."""
        yield self.raw
        yield self.result


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness(published_at: str, now: datetime, half_life_h: float = RANK_HALF_LIFE_HOURS) -> float:
    dt = _parse_dt(published_at)
    if dt is None:
        return 0.5  # زمان نامعلوم: خنثی
    age_h = max(0.0, (now - dt).total_seconds() / 3600)  # زمان آینده = تازه
    return 0.5 ** (age_h / max(half_life_h, 0.1))


def source_weight(name: str, dedicated: bool) -> float:
    if name in SOURCE_WEIGHTS:
        return _clamp(SOURCE_WEIGHTS[name])
    return RANK_DEFAULT_DEDICATED if dedicated else RANK_DEFAULT_GENERAL


def rank_items(
    pairs: Sequence[tuple],
    coverage: Mapping[str, Sequence[str]] | None = None,
    *,
    now: datetime | None = None,
) -> list[RankedItem]:
    """
    pairs: [(RawArticle, FilterResult)]. خروجی: RankedItem مرتب‌شده (بهترین اول).
    تساوی: امتیاز کلیدواژه‌ای بیشتر، سپس تازه‌تر.
    """
    now = now or datetime.now(timezone.utc)
    coverage = coverage or {}
    weights = {
        "relevance": max(0.0, RANK_W_RELEVANCE),
        "freshness": max(0.0, RANK_W_FRESHNESS),
        "source":    max(0.0, RANK_W_SOURCE),
        "coverage":  max(0.0, RANK_W_COVERAGE),
    }
    total_w = sum(weights.values()) or 1.0

    ranked: list[RankedItem] = []
    for art, res in pairs:
        n_sources = max(1, len(coverage.get(art.uid, ())))
        parts = {
            "relevance": _clamp(res.score / max(CRITICAL_SCORE_THRESHOLD, 1)),
            "freshness": _clamp(freshness(art.published_at, now)),
            "source":    source_weight(art.source, bool(getattr(art, "dedicated", False))),
            "coverage":  _clamp((n_sources - 1) / 3),
        }
        base = sum(weights[k] * parts[k] for k in weights) / total_w * 100
        bonus = RANK_CRITICAL_BONUS if getattr(res, "critical", False) else 0.0
        ranked.append(RankedItem(art, res, round(min(100.0, base + bonus), 2), parts))

    ranked.sort(
        key=lambda r: (
            -r.rank,
            -r.result.score,
            -(_parse_dt(r.raw.published_at) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
        )
    )
    return ranked
