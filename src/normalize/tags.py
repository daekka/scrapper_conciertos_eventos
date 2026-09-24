from __future__ import annotations

import unicodedata

# Etiquetas derivadas de la localización, no sugeridas por el LLM.
CITY_TAGS = {
    "a coruña": "acoruna",
    "coruña": "acoruna",
    "a coruna": "acoruna",
    "ferrol": "ferrol",
    "santiago de compostela": "santiago",
    "santiago": "santiago",
    "vigo": "vigo",
    "pontevedra": "pontevedra",
    "ourense": "ourense",
    "lugo": "lugo",
    "o grove": "ogrove",
}

PROVINCE_TAGS = {
    "a coruña": "acoruna",
    "pontevedra": "pontevedra",
    "ourense": "ourense",
    "lugo": "lugo",
}


def slug_tag(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.strip().casefold())
    ascii_text = "".join(ch for ch in folded if not unicodedata.combining(ch))
    chars = [ch if ch.isalnum() else "-" for ch in ascii_text]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def dedupe_tags(names: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        cleaned = slug_tag(name)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered
