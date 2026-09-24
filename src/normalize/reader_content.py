from __future__ import annotations

from html import escape

from src.normalize.concert_datetime import format_concert_when
from src.normalize.cookies import strip_cookie_consent
from src.normalize.tickets import normalize_ticket_url


def _heading(concert) -> str:
    return (
        getattr(concert, "artist", None)
        or getattr(concert, "event_name", None)
        or getattr(concert, "title", None)
        or "Concierto"
    )


def _place(concert) -> str:
    parts = [getattr(concert, "venue", None), getattr(concert, "city", None)]
    text = " · ".join(part for part in parts if part)
    return text or "Lugar no indicado"


def format_price_display(concert) -> str:
    if getattr(concert, "free", None):
        return "Gratuito"
    price = getattr(concert, "price", None)
    if price is not None:
        currency = getattr(concert, "currency", None)
        if currency in (None, "EUR", "€"):
            return f"{price:g} €"
        return f"{price:g} {currency}"
    return "No indicado"


def link_description(concert) -> str:
    """Descripción corta de la tarjeta KaraKeep (sin cookies)."""
    return (
        f"📅 {format_concert_when(concert)}\n"
        f"📍 {_place(concert)}\n"
        f"💰 {format_price_display(concert)}"
    )


def reader_html(concert) -> str:
    """HTML mínimo para el reader view: Cuándo / Dónde / Precio, sin CMP."""
    heading = escape(_heading(concert))
    when = escape(format_concert_when(concert))
    place = escape(_place(concert))
    price = escape(format_price_display(concert))
    description = strip_cookie_consent(getattr(concert, "description", None)) or ""
    description = escape(description)
    source = escape(getattr(concert, "source_url", None) or "")
    ticket = normalize_ticket_url(getattr(concert, "ticket_url", None))
    ticket = escape(ticket) if ticket else ""

    parts = [
        "<!DOCTYPE html>",
        '<html lang="es"><head><meta charset="utf-8">',
        f"<title>{heading}</title></head><body><article>",
        f"<h1>{heading}</h1>",
        f"<p><strong>Cuándo:</strong> {when}</p>",
        f"<p><strong>Dónde:</strong> {place}</p>",
        f"<p><strong>Precio:</strong> {price}</p>",
    ]
    if description:
        parts.append(f"<p>{description}</p>")
    if ticket:
        parts.append(f'<p><a href="{ticket}">Entradas</a></p>')
    if source:
        parts.append(f'<p><a href="{source}">Ficha en Galicia en Concierto</a></p>')
    parts.append("</article></body></html>")
    return "\n".join(parts)


def reader_content_needs_refresh(content: str | None) -> bool:
    """True si el markdown/HTML del reader tiene CMP o no trae el bloque Cuándo."""
    if not content or not content.strip():
        return False
    lower = content.casefold()
    if "utilizamos cookies" in lower or "ajustes de cookie" in lower:
        return True
    if "**cuándo:**" in lower or "**cuando:**" in lower:
        return False
    if "cuándo:" in lower or "cuando:" in lower:
        # Formato crudo de Galicia (sin negrita) → reemplazar.
        return True
    return True
