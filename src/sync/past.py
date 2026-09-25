from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.models.discovered import Concert, DiscoveredEvent


def event_end_bound(concert: Concert) -> datetime | None:
    tz = ZoneInfo(concert.timezone or "Europe/Madrid")
    if concert.end_date and concert.end_time:
        return datetime.combine(concert.end_date, concert.end_time, tzinfo=tz)
    if concert.end_date:
        return datetime.combine(concert.end_date, time(23, 59, 59), tzinfo=tz)
    if concert.date and concert.end_time:
        end_day = concert.date
        if concert.start_time and concert.end_time < concert.start_time:
            end_day = concert.date + timedelta(days=1)
        return datetime.combine(end_day, concert.end_time, tzinfo=tz)
    if concert.date and concert.start_time:
        return datetime.combine(concert.date, concert.start_time, tzinfo=tz)
    if concert.date:
        return datetime.combine(concert.date, time(23, 59, 59), tzinfo=tz)
    return None


def is_past(concert: Concert, now: datetime) -> bool:
    bound = event_end_bound(concert)
    if bound is None:
        return False
    tz = bound.tzinfo or ZoneInfo("Europe/Madrid")
    current = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    return bound < current


def is_stale(concert: Concert, now: datetime, retention_days: int) -> bool:
    """True si el fin del concierto lleva más de ``retention_days`` días."""
    bound = event_end_bound(concert)
    if bound is None:
        return False
    if retention_days < 0:
        raise ValueError("retention_days debe ser >= 0")
    tz = bound.tzinfo or ZoneInfo("Europe/Madrid")
    current = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    return bound + timedelta(days=retention_days) < current


def is_past_bounds(
    *,
    start: date | None,
    start_time: time | None,
    end: date | None,
    end_time: time | None,
    all_day: bool,
    timezone: str,
    now: datetime,
) -> bool:
    concert = Concert(
        source="test",
        source_id="t",
        source_url="https://example.com/evento/t/",
        title="t",
        date=start,
        end_date=end,
        start_time=None if all_day else start_time,
        end_time=None if all_day else end_time,
        all_day=all_day,
        timezone=timezone,
        scraped_at=now,
    )
    return is_past(concert, now)


def is_discovered_past(event: DiscoveredEvent, now: datetime, timezone: str) -> bool:
    """True solo si el listado basta para afirmar que el evento ya terminó."""
    return is_past_bounds(
        start=event.date,
        start_time=event.start_time,
        end=event.end_date,
        end_time=event.end_time,
        all_day=event.all_day,
        timezone=timezone,
        now=now,
    )
