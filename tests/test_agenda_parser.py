from datetime import datetime, timezone
from pathlib import Path

from src.sources.galicia_en_concierto.agenda_parser import parse_month_html

FIXTURE = Path(__file__).parent / "fixtures" / "month_october_2026.html"


def test_month_fixture_discovers_real_events():
    events = parse_month_html(
        FIXTURE.read_text(encoding="utf-8"),
        view_year=2026,
        view_month=10,
        source="galicia_en_concierto",
        scraped_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    by_id = {event.source_id: event for event in events}
    assert len(events) == 3

    marisco = by_id["48153:18662"]
    assert marisco.title == "Concertos do Marisco"
    assert marisco.all_day is True
    assert marisco.date.isoformat() == "2026-10-01"
    assert marisco.end_date.isoformat() == "2026-10-12"
    assert marisco.venue == "Festa do Marisco"
    assert marisco.city == "O Grove"
    assert marisco.ticket_url is None
    assert marisco.source_url == "https://galiciaenconcierto.com/evento/concertos-do-marisco/"
    assert "instance_id=18662" in marisco.detail_url

    silvia = by_id["46958:18512"]
    assert silvia.start_time.hour == 20
    assert silvia.start_time.minute == 30
    assert silvia.city == "A Coruña"
    assert silvia.venue == "Palacio de la Ópera"
    assert silvia.ticket_url == "https://entradas.ataquilla.com/es/ventaentradas"
    assert silvia.all_day is False

    marinas = by_id["47771:18520"]
    assert marinas.city == "Lugo"
    assert marinas.date.isoformat() == "2026-10-02"
    assert marinas.start_time.hour == 19
