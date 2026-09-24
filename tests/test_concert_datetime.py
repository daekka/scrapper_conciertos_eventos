from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from src.models.discovered import Concert
from src.normalize.concert_datetime import (
    concert_created_at,
    created_at_matches,
    format_created_at_api,
)


NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _concert(**kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="X",
        timezone="Europe/Madrid",
        scraped_at=NOW,
    )
    data.update(kwargs)
    return Concert(**data)


def test_summer_cest_with_time():
    # 2026-09-25 is CEST (UTC+2)
    concert = _concert(date=date(2026, 9, 25), start_time=time(22, 0))
    created = concert_created_at(concert)
    assert created == datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    assert format_created_at_api(created) == "2026-09-25T20:00:00.000Z"


def test_bookmark_title_and_when_use_day_month_year():
    from src.normalize.concert_datetime import bookmark_title, format_concert_when
    from src.storage.bookmark_note import build_note
    from src.models.classification import ClassificationResult

    concert = _concert(
        date=date(2026, 9, 25),
        start_time=time(22, 0),
        title="Lions Way",
        artist="Lions Way",
    )
    assert bookmark_title(concert) == "25-09-2026 · Lions Way"
    assert format_concert_when(concert) == "25-09-2026 · 22:00"
    note = build_note(
        concert,
        ClassificationResult(
            classification="MAYBE",
            confidence=0.5,
            reason="ok",
            matched_preferences=[],
            suggested_tags=[],
        ),
        pending=False,
    )
    assert "📅 **Cuándo:** 25-09-2026 · 22:00" in note
    assert "2026-09-25" not in note.split("<!-- gca:")[0]


def test_winter_cet_with_time():
    # 2026-01-15 is CET (UTC+1)
    concert = _concert(date=date(2026, 1, 15), start_time=time(21, 30))
    created = concert_created_at(concert)
    assert created == datetime(2026, 1, 15, 20, 30, tzinfo=timezone.utc)
    assert format_created_at_api(created) == "2026-01-15T20:30:00.000Z"


def test_date_without_time_uses_noon_madrid():
    concert = _concert(date=date(2026, 9, 25), start_time=None)
    created = concert_created_at(concert)
    local = created.astimezone(ZoneInfo("Europe/Madrid"))
    assert local.date() == date(2026, 9, 25)
    assert local.hour == 12
    assert local.minute == 0
    # Must not appear as previous calendar day in Madrid.
    assert format_created_at_api(created) == "2026-09-25T10:00:00.000Z"


def test_multi_day_uses_start_date():
    concert = _concert(
        date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
        start_time=time(19, 0),
    )
    created = concert_created_at(concert)
    assert created.astimezone(ZoneInfo("Europe/Madrid")).date() == date(2026, 7, 10)


def test_missing_date_returns_none():
    assert concert_created_at(_concert(date=None)) is None


def test_created_at_matches_normalizes_micros():
    expected = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    current = datetime(2026, 9, 25, 20, 0, 0, 123000, tzinfo=timezone.utc)
    assert created_at_matches(current, expected)
    assert not created_at_matches(None, expected)
