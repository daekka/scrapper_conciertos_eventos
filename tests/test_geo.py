from src.normalize.geo import (
    GEO_ACORUNA,
    GEO_FERROL,
    GEO_LUGO,
    GEO_OTHER,
    GEO_OURENSE,
    GEO_PONTEVEDRA,
    GEO_SANTIAGO,
    GEO_VIGO,
    fold_city,
    geo_list_key_for_city,
)


def test_fold_city_strips_accents_and_case():
    assert fold_city("  A Coruña  ") == "a coruna"
    assert fold_city("Santiago de Compostela") == "santiago de compostela"


def test_acoruna_aliases():
    for city in (
        "A Coruña",
        "A Coruna",
        "La Coruña",
        "La Coruna",
        "Acoruña",
        "Acoruna",
        "acoruña",
        "acoruna",
    ):
        assert geo_list_key_for_city(city) == GEO_ACORUNA, city


def test_bare_coruna_is_not_acoruna_city():
    assert geo_list_key_for_city("Coruña") == GEO_OTHER
    assert geo_list_key_for_city("Coruna") == GEO_OTHER
    assert geo_list_key_for_city("coruña") == GEO_OTHER
    assert geo_list_key_for_city("coruna") == GEO_OTHER


def test_category_label_is_not_used():
    # La función solo mira city; category_label no participa.
    assert geo_list_key_for_city(None) == GEO_OTHER
    assert geo_list_key_for_city("") == GEO_OTHER


def test_named_cities():
    assert geo_list_key_for_city("Santiago de Compostela") == GEO_SANTIAGO
    assert geo_list_key_for_city("Santiago") == GEO_SANTIAGO
    assert geo_list_key_for_city("Vigo") == GEO_VIGO
    assert geo_list_key_for_city("Ourense") == GEO_OURENSE
    assert geo_list_key_for_city("Orense") == GEO_OURENSE
    assert geo_list_key_for_city("Lugo") == GEO_LUGO
    assert geo_list_key_for_city("Pontevedra") == GEO_PONTEVEDRA
    assert geo_list_key_for_city("Ferrol") == GEO_FERROL


def test_nearby_towns_go_to_other_galicia():
    for city in (
        "Narón",
        "Arteixo",
        "Oleiros",
        "Culleredo",
        "Cambre",
        "Cangas",
        "Redondela",
        "Boiro",
        "O Grove",
        "Villaciudad Inventada",
    ):
        assert geo_list_key_for_city(city) == GEO_OTHER, city
