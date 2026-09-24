from __future__ import annotations

import unicodedata

# Claves internas de listas geográficas (settings / KaraKeepClient).
GEO_ACORUNA = "geo_acoruna"
GEO_VIGO = "geo_vigo"
GEO_SANTIAGO = "geo_santiago"
GEO_OURENSE = "geo_ourense"
GEO_LUGO = "geo_lugo"
GEO_PONTEVEDRA = "geo_pontevedra"
GEO_FERROL = "geo_ferrol"
GEO_OTHER = "geo_other"

GEO_LIST_KEYS = frozenset(
    {
        GEO_ACORUNA,
        GEO_VIGO,
        GEO_SANTIAGO,
        GEO_OURENSE,
        GEO_LUGO,
        GEO_PONTEVEDRA,
        GEO_FERROL,
        GEO_OTHER,
    }
)

GEO_LIST_ORDER = (
    GEO_ACORUNA,
    GEO_VIGO,
    GEO_SANTIAGO,
    GEO_OURENSE,
    GEO_LUGO,
    GEO_PONTEVEDRA,
    GEO_FERROL,
    GEO_OTHER,
)

# city normalizada (sin acentos) -> clave geo. Match exacto.
_CITY_ALIASES: dict[str, str] = {
    "a coruna": GEO_ACORUNA,
    "la coruna": GEO_ACORUNA,
    "acoruna": GEO_ACORUNA,
    "santiago de compostela": GEO_SANTIAGO,
    "santiago": GEO_SANTIAGO,
    "vigo": GEO_VIGO,
    "ourense": GEO_OURENSE,
    "orense": GEO_OURENSE,
    "lugo": GEO_LUGO,
    "pontevedra": GEO_PONTEVEDRA,
    "ferrol": GEO_FERROL,
}


def fold_city(value: str) -> str:
    """Trim, minúsculas y sin diacríticos."""
    cleaned = " ".join(value.replace("\xa0", " ").split()).casefold()
    decomposed = unicodedata.normalize("NFKD", cleaned)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def geo_list_key_for_city(city: str | None) -> str:
    """Devuelve exactamente una clave geográfica a partir de city."""
    if city is None:
        return GEO_OTHER
    folded = fold_city(city)
    if not folded:
        return GEO_OTHER
    return _CITY_ALIASES.get(folded, GEO_OTHER)


def geo_list_key_for_concert(concert) -> str:
    return geo_list_key_for_city(getattr(concert, "city", None))
