from datetime import datetime, timezone
from pathlib import Path

from src.models.discovered import DiscoveredEvent
from src.sources.galicia_en_concierto.detail_parser import concert_from_detail

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _discovered(**kwargs) -> DiscoveredEvent:
    data = dict(
        source="galicia_en_concierto",
        event_id="48250",
        instance_id="1",
        source_id="48250:1",
        source_url="https://galiciaenconcierto.com/evento/el-campus/",
        detail_url="https://galiciaenconcierto.com/evento/el-campus/",
        title="El Campus",
        scraped_at=WHEN,
    )
    data.update(kwargs)
    return DiscoveredEvent(**data)


def test_campus_detail_from_real_html():
    concert = concert_from_detail(
        (FIXTURES / "detail_campus.html").read_text(encoding="utf-8"),
        _discovered(),
        scraped_at=WHEN,
    )
    assert concert.title == "El Campus"
    assert concert.date.isoformat() == "2026-09-10"
    assert concert.start_time.hour == 19
    assert concert.end_time.hour == 19
    assert concert.end_time.minute == 15
    assert concert.venue == "Peirao de Trasatlánticos"
    assert concert.city is None
    assert concert.province == "Pontevedra"
    assert concert.field_origins["province"] == "inferred"
    assert concert.free is True
    assert concert.price is None
    assert concert.description.startswith("Lg1do")
    assert concert.published_at is not None
    assert concert.country == "España"
    assert concert.latitude is None
    assert concert.event_name is None
    assert concert.artist == "El Campus"


def test_incomplete_detail_does_not_invent_times():
    discovered = _discovered(
        title="Silvia Pérez Cruz",
        source_url="https://galiciaenconcierto.com/evento/silvia-perez-cruz-2/",
        date=None,
        venue=None,
        city=None,
    )
    concert = concert_from_detail(
        (FIXTURES / "detail_incomplete.html").read_text(encoding="utf-8"),
        discovered,
        scraped_at=WHEN,
    )
    assert concert.date is None
    assert concert.start_time is None
    assert concert.price is None
    assert concert.free is None
    assert concert.title == "Silvia Pérez Cruz"
    assert (
        concert.ticket_url
        == "https://nautico.entradas.plus/entradas/es/240926-tarde"
    )
