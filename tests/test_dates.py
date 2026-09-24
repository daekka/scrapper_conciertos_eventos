from datetime import datetime
from zoneinfo import ZoneInfo

from src.normalize.dates import parse_iso_datetime, parse_listing_when


def test_listing_time_and_range():
    timed = parse_listing_when("Oct 1 a las 8:30 pm", view_year=2026, view_month=10)
    assert timed.date.isoformat() == "2026-10-01"
    assert timed.start_time.hour == 20
    assert timed.start_time.minute == 30
    assert timed.all_day is False

    ranged = parse_listing_when(
        "Oct 1 – Oct 12 todo el día",
        view_year=2026,
        view_month=10,
    )
    assert ranged.date.isoformat() == "2026-10-01"
    assert ranged.end_date.isoformat() == "2026-10-12"
    assert ranged.all_day is True
    assert ranged.start_time is None


def test_year_rollover_from_december_view():
    parsed = parse_listing_when("Jan 5 a las 9:00 pm", view_year=2026, view_month=12)
    assert parsed.date.isoformat() == "2027-01-05"


def test_iso_offset():
    parsed = parse_iso_datetime("2026-09-24T20:00:00+02:00")
    assert parsed is not None
    madrid = parsed.astimezone(ZoneInfo("Europe/Madrid"))
    assert madrid.hour == 20
    assert madrid.date().isoformat() == "2026-09-24"
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime(None) is None


def test_post_midnight_not_used_here():
    # La hora 12:00 am se interpreta como medianoche, no como mediodía.
    from src.normalize.dates import parse_clock

    assert parse_clock("12:00 am") == datetime(2000, 1, 1, 0, 0).time()
    assert parse_clock("12:15 pm").hour == 12
