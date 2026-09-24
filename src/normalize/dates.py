from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

_MONTHS = {
    "jan": 1,
    "january": 1,
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "february": 2,
    "febrero": 2,
    "mar": 3,
    "march": 3,
    "marzo": 3,
    "apr": 4,
    "april": 4,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "june": 6,
    "junio": 6,
    "jul": 7,
    "july": 7,
    "julio": 7,
    "aug": 8,
    "august": 8,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "septiembre": 9,
    "setiembre": 9,
    "oct": 10,
    "october": 10,
    "octubre": 10,
    "nov": 11,
    "november": 11,
    "noviembre": 11,
    "dec": 12,
    "december": 12,
    "dic": 12,
    "diciembre": 12,
}

_RANGE = re.compile(
    r"(?P<m1>[A-Za-zÁÉÍÓÚáéíóúñ]+)\s+(?P<d1>\d{1,2})\s*[–—-]\s*"
    r"(?P<m2>[A-Za-zÁÉÍÓÚáéíóúñ]+)\s+(?P<d2>\d{1,2})",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"(?P<m>[A-Za-zÁÉÍÓÚáéíóúñ]+)\s+(?P<d>\d{1,2})(?:\s+a las\s+(?P<t>.+))?",
    re.IGNORECASE,
)
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|h)?", re.IGNORECASE)


@dataclass
class ParsedWhen:
    date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    all_day: bool = False


def month_number(token: str) -> int | None:
    return _MONTHS.get(token.strip().casefold().rstrip("."))


def resolve_year(event_month: int, view_year: int, view_month: int) -> int:
    if view_month >= 11 and event_month <= 2:
        return view_year + 1
    if view_month <= 2 and event_month >= 11:
        return view_year - 1
    return view_year


def parse_clock(text: str) -> time | None:
    match = _CLOCK.search(text.strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = (match.group(3) or "").lower()
    if marker == "pm" and hour < 12:
        hour += 12
    elif marker == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_listing_when(
    text: str,
    *,
    view_year: int,
    view_month: int,
    all_day_hint: bool = False,
) -> ParsedWhen:
    cleaned = " ".join(text.replace("\xa0", " ").split())
    all_day = all_day_hint or "todo el día" in cleaned.casefold() or "all day" in cleaned.casefold()
    ranged = _RANGE.search(cleaned)
    if ranged:
        month_start = month_number(ranged.group("m1"))
        month_end = month_number(ranged.group("m2"))
        if month_start and month_end:
            year_start = resolve_year(month_start, view_year, view_month)
            year_end = resolve_year(month_end, view_year, view_month)
            if month_end < month_start:
                year_end = year_start + 1
            return ParsedWhen(
                date=date(year_start, month_start, int(ranged.group("d1"))),
                end_date=date(year_end, month_end, int(ranged.group("d2"))),
                all_day=True,
            )
    single = _SINGLE.search(cleaned)
    if single and month_number(single.group("m")):
        month = month_number(single.group("m"))
        assert month is not None
        year = resolve_year(month, view_year, view_month)
        start = None if all_day else parse_clock(single.group("t") or "")
        return ParsedWhen(
            date=date(year, month, int(single.group("d"))),
            start_time=start,
            all_day=all_day,
        )
    return ParsedWhen(all_day=all_day)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    return datetime.fromisoformat(text)
