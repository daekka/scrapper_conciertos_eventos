from datetime import date, datetime, time, timezone

from src.models.discovered import Concert
from src.normalize.reader_content import (
    format_price_display,
    link_description,
    reader_content_needs_refresh,
    reader_html,
)

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _concert(**kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="Banda",
        artist="Banda",
        venue="Sala X",
        city="Vigo",
        date=date(2026, 9, 25),
        start_time=time(22, 0),
        scraped_at=NOW,
    )
    data.update(kwargs)
    return Concert(**data)


def test_link_description_and_price_euro():
    concert = _concert(price=15, currency="EUR", free=False)
    assert format_price_display(concert) == "15 €"
    text = link_description(concert)
    assert "📅 25-09-2026 · 22:00" in text
    assert "📍 Sala X · Vigo" in text
    assert "💰 15 €" in text


def test_reader_html_has_labels_no_cookies():
    html = reader_html(_concert(description="Tributo en vivo."))
    assert "<strong>Cuándo:</strong> 25-09-2026 · 22:00" in html
    assert "<strong>Dónde:</strong> Sala X · Vigo" in html
    assert "<strong>Precio:</strong> No indicado" in html
    assert "Tributo en vivo." in html
    assert "Utilizamos cookies" not in html


def test_reader_content_needs_refresh_detects_cmp_and_old_format():
    cmp = "Utilizamos cookies en nuestro sitio web ... Ajustes de Cookie."
    assert reader_content_needs_refresh(f"Cuando:\n\nSep 25\n\n{cmp}")
    assert reader_content_needs_refresh("Cuando:\n\nsala La Pecera")
    assert not reader_content_needs_refresh("**Cuándo:** 25-09-2026 · 22:00\n**Dónde:** Vigo")
    assert not reader_content_needs_refresh("")
    assert not reader_content_needs_refresh(None)
