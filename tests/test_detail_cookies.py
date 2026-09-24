from datetime import datetime, timezone
from pathlib import Path

from src.models.discovered import DiscoveredEvent
from src.sources.galicia_en_concierto.detail_parser import concert_from_detail

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 9, 23, tzinfo=timezone.utc)

CMP = (
    'Utilizamos cookies en nuestro sitio web para darle la experiencia más relevante '
    'recordando sus preferencias y visitas repetidas. Al hacer clic en "Aceptar", usted '
    "acepta el uso de TODAS las cookies. Es posible que algunos de los proveedores y Google "
    "traten tus datos personales en virtud de un interés legítimo, algo a lo que puedes "
    "oponerte gestionando los Ajustes de Cookie."
)


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


def test_parser_skips_cookie_law_info_bar_and_keeps_real_description():
    html = (FIXTURES / "detail_campus.html").read_text(encoding="utf-8")
    # Insert CMP bar and a cookie <p> before the real description.
    injection = (
        f'<div data-nosnippet="true" id="cookie-law-info-bar">'
        f'<div class="cli-bar-message">{CMP}</div></div>'
        f"<p>{CMP}</p>"
    )
    html = html.replace("<body", f"<body>{injection}", 1)
    concert = concert_from_detail(html, _discovered(), scraped_at=WHEN)
    assert concert.description is not None
    assert concert.description.startswith("Lg1do")
    assert "Utilizamos cookies" not in concert.description
    assert "Ajustes de Cookie" not in concert.description


def test_parser_ignores_cookie_only_page_description():
    html = f"""<!DOCTYPE html><html><head>
<meta property="og:description" content="" />
</head><body>
<h1 class="entry-title">Solo cookies</h1>
<div class="ai1ec-event-details">
<div class="ai1ec-hidden dt-start">2026-09-10T19:00:00+02:00</div>
<div class="ai1ec-hidden dt-end">2026-09-10T19:15:00+02:00</div>
<div class="p-location">Vigo</div>
</div>
<div id="cookie-law-info-bar"><div class="cli-bar-message">{CMP}</div></div>
<p>{CMP}</p>
</body></html>"""
    concert = concert_from_detail(
        html,
        _discovered(title="Solo cookies", source_url="https://galiciaenconcierto.com/evento/x/"),
        scraped_at=WHEN,
    )
    assert concert.description is None
