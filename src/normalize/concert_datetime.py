from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

DEFAULT_CONCERT_TZ = "Europe/Madrid"
_NOON = time(12, 0, 0)


def format_concert_day(day: date) -> str:
    """Fecha visible día-mes-año."""
    return day.strftime("%d-%m-%Y")


def format_concert_when(concert) -> str:
    """Línea de fecha/hora para la nota: dd-mm-YYYY · HH:MM."""
    day: date | None = getattr(concert, "date", None)
    if day is None:
        return "Fecha no indicada"
    end = getattr(concert, "end_date", None)
    if end and end != day:
        label = f"{format_concert_day(day)} – {format_concert_day(end)}"
    else:
        label = format_concert_day(day)
    if getattr(concert, "all_day", False):
        return f"{label} · todo el día"
    start = getattr(concert, "start_time", None)
    if start:
        # Solo hora de inicio: ai1ec suele inventar un fin +15 min poco útil.
        return f"{label} · {start.strftime('%H:%M')}"
    return label


def bookmark_title(concert) -> str:
    """Título de tarjeta: dd-mm-YYYY · nombre (año visible en la UI)."""
    name = (
        getattr(concert, "artist", None)
        or getattr(concert, "event_name", None)
        or getattr(concert, "title", None)
        or "Concierto"
    )
    day: date | None = getattr(concert, "date", None)
    if day is None:
        return str(name)[:1000]
    return f"{format_concert_day(day)} · {name}"[:1000]


def concert_created_at(
    concert,
    *,
    timezone_name: str | None = None,
) -> datetime | None:
    """Instante UTC para KaraKeep createdAt a partir de date (+ start_time).

    KaraKeep ordena por createdAt desc por defecto → conciertos más recientes primero.
    """
    day: date | None = getattr(concert, "date", None)
    if day is None:
        return None
    tz_name = timezone_name or getattr(concert, "timezone", None) or DEFAULT_CONCERT_TZ
    tz = ZoneInfo(tz_name)
    clock = getattr(concert, "start_time", None) or _NOON
    local = datetime(
        day.year,
        day.month,
        day.day,
        clock.hour,
        clock.minute,
        getattr(clock, "second", 0) or 0,
        tzinfo=tz,
    )
    return local.astimezone(timezone.utc).replace(microsecond=0)


def format_created_at_api(value: datetime) -> str:
    """ISO-8601 UTC con milisegundos, como espera KaraKeep."""
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def created_at_matches(current: datetime | None, expected: datetime) -> bool:
    if current is None:
        return False
    left = current.astimezone(timezone.utc).replace(microsecond=0)
    right = expected.astimezone(timezone.utc).replace(microsecond=0)
    return left == right


def parse_api_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).replace(microsecond=0)
    except ValueError:
        return None
