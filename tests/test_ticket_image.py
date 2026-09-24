from src.normalize.ticket_image import extract_ticket_image_url, is_galicia_url


def test_extract_og_image_from_ticket_html():
    html = """
    <html><head>
      <meta property="og:image" content="https://cdn.example/poster/event.jpeg?v=1" />
    </head><body></body></html>
    """
    assert (
        extract_ticket_image_url(html, page_url="https://entradium.com/es/events/x")
        == "https://cdn.example/poster/event.jpeg?v=1"
    )


def test_rejects_galicia_image():
    html = """
    <meta property="og:image" content="https://galiciaenconcierto.com/wp-content/x.jpg" />
    """
    assert extract_ticket_image_url(html, page_url="https://tickets.example/e") is None


def test_is_galicia_url():
    assert is_galicia_url("https://galiciaenconcierto.com/evento/x/")
    assert not is_galicia_url("https://entradium.com/es/events/x")
