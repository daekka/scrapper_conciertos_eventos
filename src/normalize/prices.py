from __future__ import annotations

import re

_FREE = re.compile(r"\b(gratuito|gratis|entrada libre|entrada gratuita|free)\b", re.I)
_AMOUNT = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€|€\s*(\d+(?:[.,]\d{1,2})?)")


def parse_price(text: str | None) -> tuple[float | None, str | None, bool | None]:
    """Devuelve (precio, moneda, gratuito). None si el texto no lo dice."""
    if text is None:
        return None, None, None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None, None, None
    if _FREE.search(cleaned):
        return None, None, True
    match = _AMOUNT.search(cleaned)
    if not match:
        return None, None, None
    raw = match.group(1) or match.group(2)
    return float(raw.replace(",", ".")), "EUR", False
