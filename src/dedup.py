"""
dedup.py — حذف تکراری بین منابع (مرحله ۲ / آیتم ۲)
نسخه: 4.5.0

سه لایه، از ارزان به گران:
  ۱) URL کانونی: همان لینک با utm_*/fbclid/www/http↔https/اسلش آخر متفاوت
     (uid بر پایهٔ sha256(link) است، پس این‌ها uid متفاوت می‌گرفتند)
  ۲) عنوان نرمال‌شده یکسان (یکسان‌سازی ی/ک عربی، ارقام، نیم‌فاصله، اعراب)
  ۳) شباهت فازی: Jaccard کلمات / containment / difflib، فقط در پنجرهٔ زمانی

مقایسه با: خبرهای ذخیره‌شده (قبلاً ارسال شده → این یکی حذف می‌شود) و
خبرهای هم‌ران (بهترین نگه داشته می‌شود و منبع بقیه در coverage ثبت می‌شود
تا امتیازدهی «پوشش چندمنبعی» را مهم‌تر بداند).

فقط stdlib. به RawArticle/FilterResult وابستگی ساختاری ندارد (duck typing).
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit

from src.config import (
    DEDUP_JACCARD,
    DEDUP_RATIO,
    DEDUP_WINDOW_HOURS,
)

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# نرمال‌سازی متن فارسی
# ══════════════════════════════════════════════════════════════════════════════
_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و",
    "‌": " ", "​": " ", "‍": " ", " ": " ", "ـ": "",
    **{ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")},
    **{ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")},
})
_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")

# کلمات پرتکرار که شباهت را کاذب بالا می‌برند
_STOPWORDS = frozenset("""
از در به با که را این آن و یا تا برای است شد شده می بر هم یک ها های
شود کرد کند دارد بود خود ای نیز اما اگر پس تر ترین هر همه بین روی
""".split())


def normalize_text(text: str) -> str:
    """متن → شکل کانونی (برای مقایسه، نه نمایش)."""
    if not text:
        return ""
    text = text.translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    text = _NON_WORD.sub(" ", text.casefold())
    return _SPACES.sub(" ", text).strip()


def title_tokens(text: str) -> frozenset[str]:
    """مجموعهٔ کلمات معنادار عنوان."""
    return frozenset(
        t for t in normalize_text(text).split() if len(t) > 1 and t not in _STOPWORDS
    )


_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|igshid|mc_(cid|eid)|ref_src|_ga|yclid)$", re.I)


def canonical_url(url: str) -> str:
    """URL → کلید مستقل از scheme/www/fragment/پارامتر ردیابی/اسلش آخر."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip().lower()
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path.rstrip("/") or ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)))
    return f"{host}{path}" + (f"?{query}" if query else "")


# ══════════════════════════════════════════════════════════════════════════════
# شباهت
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class _Sig:
    norm: str
    tokens: frozenset[str]
    published: datetime | None
    source: str
    ref: Any = None   # خود article (برای in-batch)


def similar(a: _Sig, b: _Sig, *, jaccard: float, ratio: float) -> bool:
    """آیا دو عنوان یک خبر واحدند؟"""
    if not a.tokens or not b.tokens:
        return False
    inter = len(a.tokens & b.tokens)
    if inter == 0:
        return False
    union = len(a.tokens | b.tokens)
    if len(a.tokens) >= 3 and len(b.tokens) >= 3 and inter / union >= jaccard:
        return True
    # یک عنوان بسط‌یافتهٔ دیگری (مثلاً با پسوند «+ عکس»)
    if min(len(a.tokens), len(b.tokens)) >= 4 and inter / min(len(a.tokens), len(b.tokens)) >= 0.85:
        return True
    # پیش‌فیلتر ارزان قبل از difflib
    if inter / union >= 0.35:
        return difflib.SequenceMatcher(None, a.norm, b.norm).ratio() >= ratio
    return False


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _within(a: datetime | None, b: datetime | None, window: timedelta) -> bool:
    """اگر زمان یکی نامعلوم بود، محافظه‌کارانه «نزدیک» فرض می‌شود."""
    if a is None or b is None:
        return True
    return abs(a - b) <= window


# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Dropped:
    article: Any
    reason: str          # url | title | similar
    against: str         # عنوان خبری که با آن تکراری شناخته شد
    stored: bool         # True: با خبر ذخیره‌شده؛ False: با خبر هم‌ران


@dataclass
class DedupResult:
    kept: list[tuple]                                   # [(article, result), ...]
    dropped: list[Dropped] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)  # uid نگه‌داشته‌شده → منابع (شامل خودش)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"url": 0, "title": 0, "similar": 0}
        for d in self.dropped:
            out[d.reason] += 1
        return out


def _sort_key(pair: tuple) -> tuple:
    art, res = pair
    pub = _parse_dt(getattr(art, "published_at", "")) or datetime.max.replace(tzinfo=timezone.utc)
    # امتیاز بالاتر، منبع اختصاصی، قدیمی‌تر (منبع اصلی خبر) اول
    return (-getattr(res, "score", 0), not getattr(art, "dedicated", False), pub)


def dedupe(
    pairs: Sequence[tuple],
    stored_items: Iterable[Any] = (),
    *,
    window_hours: float = DEDUP_WINDOW_HOURS,
    jaccard: float = DEDUP_JACCARD,
    ratio: float = DEDUP_RATIO,
) -> DedupResult:
    """
    pairs: [(RawArticle, FilterResult)]  — خروجی filter_articles
    stored_items: آیتم‌های ذخیره‌شده (NewsItem: title, link, published_at)
    """
    window = timedelta(hours=window_hours)

    stored_urls: dict[str, str] = {}
    stored_titles: dict[str, str] = {}
    stored_sigs: list[tuple[_Sig, str]] = []
    for it in stored_items:
        title = getattr(it, "title", "") or ""
        norm = normalize_text(title)
        stored_urls.setdefault(canonical_url(getattr(it, "link", "")), title)
        if norm:
            stored_titles.setdefault(norm, title)
        stored_sigs.append((
            _Sig(norm, title_tokens(title), _parse_dt(getattr(it, "published_at", "")),
                 getattr(it, "source", "")),
            title,
        ))

    kept: list[tuple] = []
    kept_sigs: list[_Sig] = []
    kept_urls: dict[str, Any] = {}
    kept_titles: dict[str, Any] = {}
    result = DedupResult(kept=kept)

    def _note_coverage(winner: Any, source: str) -> None:
        srcs = result.coverage.setdefault(winner.uid, [winner.source])
        if source and source not in srcs:
            srcs.append(source)

    for pair in sorted(pairs, key=_sort_key):
        art = pair[0]
        norm = normalize_text(art.title)
        sig = _Sig(norm, title_tokens(art.title), _parse_dt(getattr(art, "published_at", "")),
                   art.source, art)
        url_key = canonical_url(art.link)

        # ۱) URL
        if url_key in stored_urls:
            result.dropped.append(Dropped(art, "url", stored_urls[url_key], True))
            continue
        if url_key in kept_urls:
            _note_coverage(kept_urls[url_key], art.source)
            result.dropped.append(Dropped(art, "url", kept_urls[url_key].title, False))
            continue

        # ۲) عنوان یکسان
        if norm and norm in stored_titles:
            result.dropped.append(Dropped(art, "title", stored_titles[norm], True))
            continue
        if norm and norm in kept_titles:
            _note_coverage(kept_titles[norm], art.source)
            result.dropped.append(Dropped(art, "title", kept_titles[norm].title, False))
            continue

        # ۳) فازی
        hit = next(
            ((t, True, None) for s, t in stored_sigs
             if _within(sig.published, s.published, window)
             and similar(sig, s, jaccard=jaccard, ratio=ratio)),
            None,
        )
        if hit is None:
            ks = next((k for k in kept_sigs
                       if _within(sig.published, k.published, window)
                       and similar(sig, k, jaccard=jaccard, ratio=ratio)), None)
            if ks is not None:
                _note_coverage(ks.ref, art.source)
                result.dropped.append(Dropped(art, "similar", ks.ref.title, False))
                continue
        else:
            result.dropped.append(Dropped(art, "similar", hit[0], True))
            continue

        kept.append(pair)
        kept_sigs.append(sig)
        kept_urls[url_key] = art
        if norm:
            kept_titles[norm] = art

    if result.dropped:
        c = result.counts
        log.info("🔁 dedup: %d تکراری حذف شد (URL=%d، عنوان=%d، مشابه=%d)",
                 len(result.dropped), c["url"], c["title"], c["similar"])
        for d in result.dropped[:10]:
            log.debug("   ↳ [%s] «%s» ≈ «%s»", d.reason, d.article.title[:50], d.against[:50])
    return result
