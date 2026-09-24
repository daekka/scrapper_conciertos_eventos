from src.normalize.cookies import (
    description_needs_cookie_cleanup,
    is_cookie_consent_text,
    note_contains_cookie_consent,
    strip_cookie_consent,
)

REAL_CMP = (
    'Utilizamos cookies en nuestro sitio web para darle la experiencia más relevante '
    'recordando sus preferencias y visitas repetidas. Al hacer clic en "Aceptar", usted '
    "acepta el uso de TODAS las cookies. Es posible que algunos de los proveedores y Google "
    "traten tus datos personales en virtud de un interés legítimo, algo a lo que puedes "
    "oponerte gestionando los Ajustes de Cookie."
)

REAL_CMP_MD = (
    REAL_CMP
    + " [política de privacidad](https://galiciaenconcierto.com/politica-de-privacidad/)"
)

REAL_CMP_HTML = (
    '<div id="cookie-law-info-bar"><div class="cli-bar-message">'
    + REAL_CMP
    + ' <a href="https://galiciaenconcierto.com/politica-de-privacidad/">proveedores</a>'
    + "</div></div>"
)


def test_strips_real_cookie_paragraph():
    assert strip_cookie_consent(REAL_CMP) is None
    assert not is_cookie_consent_text(strip_cookie_consent(REAL_CMP))


def test_strips_multiline_and_spacing_variants():
    spaced = REAL_CMP.replace(" ", "  ").replace(". ", ".\n\n")
    assert strip_cookie_consent(spaced) is None


def test_strips_markdown_privacy_link_in_cmp():
    cleaned = strip_cookie_consent(REAL_CMP_MD)
    assert cleaned is None
    assert "politica-de-privacidad" not in (cleaned or "")


def test_strips_html_cmp_blob():
    assert strip_cookie_consent(REAL_CMP_HTML) is None


def test_strips_ajustes_de_cookie_block():
    assert "Ajustes de Cookie" in REAL_CMP
    assert strip_cookie_consent(REAL_CMP) is None


def test_preserves_legitimate_description():
    text = (
        "Power trio de rock con influencias de hard rock clásico. "
        "Entradas a la venta en la web de los proveedores del recinto."
    )
    assert strip_cookie_consent(text) == text
    assert not is_cookie_consent_text(text)
    assert not description_needs_cookie_cleanup(text)


def test_generic_privacidad_alone_is_kept():
    text = "Más info en la política de privacidad del festival."
    assert strip_cookie_consent(text) == text
    assert not description_needs_cookie_cleanup(text)


def test_cookie_plus_real_description_keeps_real_part():
    mixed = REAL_CMP + "\n\nTributo a Nirvana en sala La Pecera."
    cleaned = strip_cookie_consent(mixed)
    assert cleaned is not None
    assert "Utilizamos cookies" not in cleaned
    assert "Ajustes de Cookie" not in cleaned
    assert "Tributo a Nirvana" in cleaned


def test_note_detection():
    note = f"# X\n\n{REAL_CMP}\n\n<!-- gca:meta {{}} -->\n"
    assert note_contains_cookie_consent(note)
    assert not note_contains_cookie_consent("# X\n\nBuen concierto de rock.\n")
