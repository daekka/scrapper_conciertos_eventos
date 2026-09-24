from datetime import datetime, timezone

from src.models.discovered import DiscoveredEvent
from src.normalize.listing_fingerprint import listing_fingerprint


def _event(**kwargs) -> DiscoveredEvent:
    base = dict(
        source="galicia_en_concierto",
        event_id="1",
        instance_id="2",
        source_id="1:2",
        source_url="https://galiciaenconcierto.com/evento/x/",
        detail_url="https://galiciaenconcierto.com/evento/x/?instance_id=2",
        title="Banda",
        venue="Sala",
        city="Vigo",
        scraped_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return DiscoveredEvent(**base)


def test_fingerprint_ignores_fields_absent_from_listing_model():
    assert "description" not in DiscoveredEvent.model_fields
    left = listing_fingerprint(_event())
    right = listing_fingerprint(_event())
    assert left == right
    assert listing_fingerprint(_event(venue="Otra sala")) != left


def test_fingerprint_changes_on_date_or_ticket():
    from datetime import date, time

    base = listing_fingerprint(_event(date=date(2026, 10, 1), start_time=time(20, 0)))
    moved = listing_fingerprint(_event(date=date(2026, 10, 2), start_time=time(20, 0)))
    retimed = listing_fingerprint(_event(date=date(2026, 10, 1), start_time=time(21, 0)))
    ticket = listing_fingerprint(
        _event(
            date=date(2026, 10, 1),
            start_time=time(20, 0),
            ticket_url="https://tickets.example/a",
        )
    )
    assert len({base, moved, retimed, ticket}) == 4
