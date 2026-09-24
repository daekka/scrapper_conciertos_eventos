from src.normalize.urls import canonicalize_url


def test_canonical_event_url_strips_tracking_and_instance():
    raw = (
        "HTTPS://GaliciaEnConcierto.com/evento/silvia-perez-cruz/"
        "?instance_id=18512&utm_source=ig&fbclid=abc&keep=1#foto"
    )
    assert (
        canonicalize_url(raw, force_trailing_slash=True)
        == "https://galiciaenconcierto.com/evento/silvia-perez-cruz/?keep=1"
    )


def test_adds_trailing_slash_only_when_requested():
    assert (
        canonicalize_url("https://example.com/evento/foo", force_trailing_slash=True)
        == "https://example.com/evento/foo/"
    )
    assert (
        canonicalize_url("https://tickets.example/es/venta", force_trailing_slash=False)
        == "https://tickets.example/es/venta"
    )
