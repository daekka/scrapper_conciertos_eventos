from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.sync.past import is_past_bounds

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
