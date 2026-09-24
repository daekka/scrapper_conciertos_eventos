from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from src.models.discovered import DiscoveredEvent
from src.sync.past import is_discovered_past

TZ = "Europe/Madrid"
NOW = datetime(2026, 9, 23, 21, 0, tzinfo=ZoneInfo(TZ))


def _event(**kwargs) -> DiscoveredEvent:
    data = dict(
        source="galicia_en_concierto",
        event_id="1",
        instance_id="1",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        detail_url="https://galiciaenconcierto.com/evento/x/?instance_id=1",
        title="Evento",
        scraped_at=NOW,
    )
    data.update(kwargs)
    return DiscoveredEvent(**data)


def test_past_listing_is_omitted():
    event = _event(date=date(2026, 9, 20), start_time=time(20, 0))
    assert is_discovered_past(event, NOW, TZ) is True


def test_future_listing_is_kept():
    event = _event(date=date(2026, 12, 1), start_time=time(21, 0))
    assert is_discovered_past(event, NOW, TZ) is False


def test_today_still_ongoing_is_kept():
    event = _event(date=date(2026, 9, 23), start_time=time(22, 0))
    assert is_discovered_past(event, NOW, TZ) is False


def test_today_already_finished_is_omitted():
    event = _event(
        date=date(2026, 9, 23),
        start_time=time(18, 0),
        end_time=time(20, 0),
    )
    assert is_discovered_past(event, NOW, TZ) is True


def test_today_all_day_is_kept_until_end_of_day():
    event = _event(date=date(2026, 9, 23), all_day=True)
    assert is_discovered_past(event, NOW, TZ) is False
    after_midnight = datetime(2026, 9, 24, 0, 0, 1, tzinfo=ZoneInfo(TZ))
    assert is_discovered_past(event, after_midnight, TZ) is True


def test_incomplete_listing_without_date_is_kept():
    event = _event(date=None, start_time=None, end_date=None, end_time=None)
    assert is_discovered_past(event, NOW, TZ) is False


def test_discover_omits_past_without_detail_fetch(monkeypatch):
    from src.http.client import HttpClient
    from src.sources.galicia_en_concierto.source import GaliciaEnConciertoSource

    listing = [
        _event(
            source_id="10:20",
            title="Pasado",
            date=date(2026, 9, 20),
            start_time=time(20, 0),
        ),
        _event(
            source_id="11:21",
            title="Hoy",
            date=date(2026, 9, 23),
            start_time=time(22, 0),
        ),
        _event(
            source_id="12:22",
            title="Sin fecha",
            date=None,
            start_time=None,
        ),
        _event(
            source_id="13:23",
            title="Futuro",
            date=date(2026, 12, 1),
            start_time=time(21, 0),
        ),
    ]
    monkeypatch.setattr(
        "src.sources.galicia_en_concierto.source.parse_month_html",
        lambda *args, **kwargs: listing,
    )
    http = HttpClient(timeout=1, retries=1, backoff_seconds=0, user_agent="test", delay=0)
    source = GaliciaEnConciertoSource(
        http=http,
        base_url="https://galiciaenconcierto.com",
        agenda_path="/agenda-conciertos-galicia",
        months_ahead=1,
        timezone_name=TZ,
    )
    monkeypatch.setattr(http, "get_text", lambda url: "<html/>")
    detail_calls: list[str] = []

    def _boom(event):
        detail_calls.append(event.source_id)
        raise AssertionError("no debe pedirse la ficha en discovery")

    monkeypatch.setattr(source, "fetch_detail", _boom)
    events = source.discover(now=NOW.astimezone(timezone.utc))
    assert {event.title for event in events} == {"Hoy", "Sin fecha", "Futuro"}
    assert detail_calls == []
    http.close()
