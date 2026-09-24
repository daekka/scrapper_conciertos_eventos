from __future__ import annotations

from html import unescape
from urllib.parse import urlsplit, urlunsplit

from src.sync.identity import event_key


def normalize_ticket_url(url: str | None) -> str | None:
    """Normaliza URL de entradas conservando query params (incl. tracking).

    No elimina utm_/fbclid/etc.: suelen ser necesarios en links de ticketing.
    Rechaza vacíos, '#' y esquemas no http(s).
    """
    if url is None:
        return None
    raw = unescape(str(url)).strip()
    if not raw or raw == "#":
        return None
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        return None
    netloc = parts.netloc.lower()
    if not netloc:
        return None
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def prefer_ticket_url(incoming: str | None, previous: str | None) -> str | None:
    """Elige URL de entradas sin borrar una válida con null/vacío."""
    new = normalize_ticket_url(incoming)
    if new:
        return new
    return normalize_ticket_url(previous)


def bookmark_card_url(*, source_url: str, ticket_url: str | None) -> str:
    """URL de la tarjeta KaraKeep: entradas si existen; si no, ficha Galicia."""
    ticket = normalize_ticket_url(ticket_url)
    if ticket:
        return ticket
    return event_key(source_url)


def card_urls_match(current: str | None, desired: str | None) -> bool:
    if not current or not desired:
        return False
    left = normalize_ticket_url(current) or current.rstrip("/")
    right = normalize_ticket_url(desired) or desired.rstrip("/")
    if "galiciaenconcierto.com" in left.lower() or "galiciaenconcierto.com" in right.lower():
        return event_key(left) == event_key(right)
    return left == right


def note_has_entradas_link(note: str | None) -> bool:
    if not note:
        return False
    visible = note.split("<!-- gca:", 1)[0]
    return "[Entradas](" in visible
