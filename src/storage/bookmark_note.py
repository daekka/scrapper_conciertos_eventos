from __future__ import annotations

import json
import re

from src.models.classification import ClassificationResult
from src.models.discovered import Concert
from src.normalize.concert_datetime import format_concert_when
from src.normalize.cookies import strip_cookie_consent
from src.normalize.genres import format_genres_display
from src.normalize.reader_content import format_price_display
from src.normalize.tickets import normalize_ticket_url

_ANALYSIS_RE = re.compile(
    r"<!-- gca:analysis-start -->(.*)<!-- gca:analysis-end -->",
    re.S,
)
_META_RE = re.compile(r"<!-- gca:meta (\{.*?\}) -->", re.S)
_CONCERT_RE = re.compile(r"<!-- gca:concert (\{.*?\}) -->", re.S)


def _safe_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("-->", "-- >")


def parse_meta(note: str | None) -> dict:
    if not note:
        return {}
    match = _META_RE.search(note)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def parse_stored_concert(note: str | None) -> Concert | None:
    if not note:
        return None
    match = _CONCERT_RE.search(note)
    if not match:
        return None
    try:
        return Concert.model_validate(json.loads(match.group(1)))
    except (json.JSONDecodeError, ValueError):
        return None


def extract_analysis(note: str | None) -> str | None:
    if not note:
        return None
    match = _ANALYSIS_RE.search(note)
    if not match:
        return None
    return f"<!-- gca:analysis-start -->{match.group(1)}<!-- gca:analysis-end -->\n"


def _when(concert: Concert) -> str:
    return format_concert_when(concert)


def _place(concert: Concert) -> str:
    parts = [concert.venue, concert.city]
    text = " · ".join(part for part in parts if part)
    return text or "Lugar no indicado"


def analysis_block(result: ClassificationResult | None) -> str:
    if result is None:
        body = "Pendiente de clasificación.\n"
    else:
        lines = [f"- {item}" for item in result.matched_preferences] or ["- Ninguna indicada"]
        body = (
            f"{result.reason}\n\n"
            f"**Clasificación:** {result.classification}\n"
            f"**Confianza:** {round(result.confidence * 100)}%\n\n"
            "### Coincidencias\n"
            + "\n".join(lines)
            + "\n"
        )
    return f"<!-- gca:analysis-start -->\n## 🤖 Análisis\n\n{body}\n<!-- gca:analysis-end -->\n"


def _facts(concert: Concert) -> str:
    heading = concert.artist or concert.event_name or concert.title
    description = strip_cookie_consent(concert.description) or ""
    description_block = f"\n{description}\n" if description else "\n"
    genres_line = format_genres_display(concert.genres)
    ticket = normalize_ticket_url(concert.ticket_url)
    ticket_line = f"\n🎫 **[Entradas]({ticket})**\n" if ticket else ""
    return (
        f"# {heading}\n\n"
        f"📅 **Cuándo:** {_when(concert)}\n"
        f"📍 **Dónde:** {_place(concert)}\n"
        f"🎸 **Género:** {genres_line}\n"
        f"💰 **Precio:** {format_price_display(concert)}\n"
        f"{ticket_line}"
        f"{description_block}"
    )


def _info(concert: Concert) -> str:
    rows = [
        ("Artista", concert.artist),
        ("Recinto", concert.venue),
        ("Ciudad", concert.city),
        ("Provincia", concert.province),
        ("Fuente", concert.source_url),
        ("Publicado", concert.published_at.isoformat() if concert.published_at else None),
        ("Detectado", concert.scraped_at.isoformat()),
    ]
    lines = "\n".join(f"- {label}: {value}" for label, value in rows if value)
    return f"## Información\n{lines}\n"


def _hidden(concert: Concert, classification_name: str | None, pending: bool) -> str:
    meta = {
        "listing_fp": concert.listing_fingerprint,
        "source_id": concert.source_id,
        "classification": classification_name,
        "pending": pending,
    }
    concert_json = _safe_json(concert.model_dump(mode="json"))
    return f"<!-- gca:meta {_safe_json(meta)} -->\n<!-- gca:concert {concert_json} -->\n"


def build_note(
    concert: Concert,
    result: ClassificationResult | None,
    *,
    pending: bool,
    preserved_analysis: str | None = None,
    classification_name: str | None = None,
) -> str:
    cleaned = strip_cookie_consent(concert.description)
    if cleaned != concert.description:
        concert.description = cleaned
    normalized_ticket = normalize_ticket_url(concert.ticket_url)
    if normalized_ticket != concert.ticket_url:
        concert.ticket_url = normalized_ticket
    analysis = preserved_analysis or analysis_block(None if pending else result)
    stored = None if pending else (result.classification if result else classification_name)
    return _facts(concert) + "\n" + analysis + "\n" + _info(concert) + "\n" + _hidden(
        concert, stored, pending
    )
