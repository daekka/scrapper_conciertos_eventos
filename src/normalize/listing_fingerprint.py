from __future__ import annotations

import hashlib

from src.models.discovered import DiscoveredEvent


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def listing_fingerprint(event: DiscoveredEvent) -> str:
    """Huella del listado. No incluye descripción: la agenda no la trae completa."""
    keywords = getattr(event, "keywords", None) or []
    parts = [
        _norm(event.title),
        event.date.isoformat() if event.date else "",
        event.end_date.isoformat() if event.end_date else "",
        event.start_time.isoformat() if event.start_time else "",
        event.end_time.isoformat() if event.end_time else "",
        _norm(event.venue),
        _norm(event.city),
        event.ticket_url or "",
        "1" if event.all_day else "0",
    ]
    if keywords:
        parts.append(",".join(sorted(_norm(k) for k in keywords if k)))
    image_url = getattr(event, "image_url", None) or ""
    if image_url:
        parts.append(_norm(image_url))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
