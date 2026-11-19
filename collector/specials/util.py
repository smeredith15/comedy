"""Small helpers: slugs, name normalization, dates, durations."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slugify(text: str) -> str:
    text = ascii_fold(text or "").lower().replace("&", " and ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"


def norm(text: str) -> str:
    """Lowercase, accents and punctuation removed, single spaces. For comparisons."""
    text = ascii_fold(text or "").lower().replace("&", " and ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_loose_date(text: str, default_year: int | None = None,
                     default_month: int | None = None) -> dt.date | None:
    """Parse 'January 5', 'January 5, 2024', '5 January 2024', '2024-01-05', or a bare day."""
    if not text:
        return None
    t = re.sub(r"\[[^\]]*\]", "", text)          # footnote markers
    t = t.replace(",", " ").replace(".", " ").strip().lower()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    words = t.split()
    year = next((int(w) for w in words if re.fullmatch(r"\d{4}", w)), default_year)
    month = next((_MONTHS[w] for w in words if w in _MONTHS), None)
    day = next((int(w) for w in words if re.fullmatch(r"\d{1,2}", w)), None)
    if month is None:
        month = default_month
    if year and month and day:
        return _safe_date(year, month, day)
    return None


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def month_from_text(text: str) -> int | None:
    for w in norm(text).split():
        if w in _MONTHS and len(w) > 3:
            return _MONTHS[w]
    return None


def parse_iso_duration_minutes(value: str | None) -> int | None:
    """YouTube's ISO 8601 durations, e.g. PT1H2M10S -> 62."""
    if not value:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return round((d * 86400 + h * 3600 + mi * 60 + s) / 60)


def contains_phrase(text: str, phrase: str) -> bool:
    return f" {norm(phrase)} " in f" {norm(text)} "
