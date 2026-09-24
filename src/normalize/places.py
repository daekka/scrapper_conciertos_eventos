from __future__ import annotations

CITY_PROVINCE = {
    "a coruña": "A Coruña",
    "coruña": "A Coruña",
    "a coruna": "A Coruña",
    "ferrol": "A Coruña",
    "santiago de compostela": "A Coruña",
    "santiago": "A Coruña",
    "cambre": "A Coruña",
    "boiro": "A Coruña",
    "oleiros": "A Coruña",
    "arteixo": "A Coruña",
    "pontedeume": "A Coruña",
    "sigüeiro": "A Coruña",
    "siguiero": "A Coruña",
    "o grove": "Pontevedra",
    "grove": "Pontevedra",
    "vigo": "Pontevedra",
    "pontevedra": "Pontevedra",
    "cangas": "Pontevedra",
    "sanxenxo": "Pontevedra",
    "ourense": "Ourense",
    "lugo": "Lugo",
    "lobios": "Ourense",
}

CATEGORY_PROVINCE = {
    "coruña": "A Coruña",
    "a coruña": "A Coruña",
    "pontevedra": "Pontevedra",
    "ourense": "Ourense",
    "orense": "Ourense",
    "lugo": "Lugo",
    "santiago": "A Coruña",
}


def split_location(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    cleaned = " ".join(text.replace("\xa0", " ").split()).lstrip("@").strip()
    if not cleaned:
        return None, None
    if "," in cleaned:
        venue, city = cleaned.rsplit(",", 1)
        return venue.strip() or None, city.strip() or None
    if cleaned.casefold() in CITY_PROVINCE:
        return None, cleaned
    return cleaned, None


def province_for_city(city: str | None) -> str | None:
    if not city:
        return None
    return CITY_PROVINCE.get(city.casefold())


def province_for_category(label: str | None) -> str | None:
    if not label:
        return None
    return CATEGORY_PROVINCE.get(label.strip().casefold())
