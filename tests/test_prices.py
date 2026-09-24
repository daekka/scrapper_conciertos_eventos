from src.normalize.prices import parse_price


def test_free_and_numeric_prices():
    assert parse_price("Gratuito") == (None, None, True)
    assert parse_price("Entrada gratuita") == (None, None, True)
    assert parse_price("15 €") == (15.0, "EUR", False)
    assert parse_price("15,50€") == (15.5, "EUR", False)
    assert parse_price("€ 12") == (12.0, "EUR", False)


def test_unknown_price_is_empty():
    assert parse_price("") == (None, None, None)
    assert parse_price(None) == (None, None, None)
    assert parse_price("consultar taquilla") == (None, None, None)
