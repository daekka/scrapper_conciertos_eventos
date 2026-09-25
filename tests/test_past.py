from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.models.discovered import Concert
from src.sync.past import is_past_bounds, is_stale

TZ = "Europe/Madrid"
NOW = datetime(2026, 9, 24, 0, 30, tzinfo=ZoneInfo(TZ))


def test_post_midnight_still_ongoing():
    assert (
        is_past_bounds(
            start=date(2026, 9, 23),
            start_time=time(23, 30),
            end=None,
            end_time=time(1, 0),
            all_day=False,
            timezone=TZ,
            now=NOW,
        )
        is False
    )


def test_finished_after_end():
    assert (
        is_past_bounds(
            start=date(2026, 9, 23),
            start_time=time(23, 30),
            end=None,
            end_time=time(0, 15),
            all_day=False,
            timezone=TZ,
            now=NOW,
        )
        is True
    )


def test_multiday_not_past_on_first_day():
    assert (
        is_past_bounds(
            start=date(2026, 9, 23),
            start_time=None,
            end=date(2026, 9, 27),
            end_time=None,
            all_day=True,
            timezone=TZ,
            now=datetime(2026, 9, 24, 12, 0, tzinfo=ZoneInfo(TZ)),
        )
        is False
    )


def test_multiday_past_after_last_day():
    assert (
        is_past_bounds(
            start=date(2026, 9, 23),
            start_time=None,
            end=date(2026, 9, 27),
            end_time=None,
            all_day=True,
            timezone=TZ,
            now=datetime(2026, 9, 28, 0, 1, tzinfo=ZoneInfo(TZ)),
        )
        is True
    )


def test_unknown_date_is_not_past():
    assert (
        is_past_bounds(
            start=None,
            start_time=None,
            end=None,
            end_time=None,
            all_day=False,
            timezone=TZ,
            now=NOW,
        )
        is False
    )


def _concert_for_stale(*, day: date, start: time) -> Concert:
    return Concert(
        source="test",
        source_id="t",
        source_url="https://example.com/evento/t/",
        title="t",
        date=day,
        start_time=start,
        timezone=TZ,
        scraped_at=NOW,
    )


def test_is_stale_false_at_exact_retention_boundary():
    concert = _concert_for_stale(day=date(2026, 9, 16), start=time(20, 0))
    now = datetime(2026, 9, 23, 20, 0, tzinfo=ZoneInfo(TZ))
    assert is_stale(concert, now, retention_days=7) is False


def test_is_stale_true_just_after_retention():
    concert = _concert_for_stale(day=date(2026, 9, 16), start=time(20, 0))
    now = datetime(2026, 9, 23, 20, 0, 1, tzinfo=ZoneInfo(TZ))
    assert is_stale(concert, now, retention_days=7) is True


def test_is_stale_false_within_retention_window():
    concert = _concert_for_stale(day=date(2026, 9, 20), start=time(20, 0))
    now = datetime(2026, 9, 23, 12, 0, tzinfo=ZoneInfo(TZ))
    assert is_stale(concert, now, retention_days=7) is False
