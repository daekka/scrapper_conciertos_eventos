from __future__ import annotations

import re
from html import unescape

# Selectores del CMP Cookie Law Info / similares en Galicia en Concierto.
CMP_SELECTORS = (
    "#cookie-law-info-bar",
    "#cookie-law-info-again",
    "#cliSettingsPopup",
    "#cli-cookie-button",
    ".cli-modal",
    ".cli-modal-dialog",
    ".cli-bar-container",
    ".cli-bar-message",
    ".wt-cli-cookie-bar",
    ".moove-gdpr-info-bar-container",
    "#moove_gdpr_cookie_info_bar",
)

_STRONG = (
    re.compile(r"utilizamos\s+cookies\s+en\s+nuestro\s+sitio\s+web", re.I),
    re.compile(r"acepta\s+el\s+uso\s+de\s+todas\s+las\s+cookies", re.I),
    re.compile(r"ajustes\s+de\s+cookie", re.I),
    re.compile(r"experiencia\s+m[aá]s\s+relevante", re.I),
    re.compile(r"recordando\s+sus\s+preferencias", re.I),
    re.compile(r"al\s+hacer\s+clic\s+en\s+[\"“]?aceptar", re.I),
    re.compile(r"inter[eé]s\s+leg[ií]timo", re.I),
    re.compile(r"politica-de-privacidad", re.I),
    re.compile(r"pol[ií]tica\s+de\s+privacidad", re.I),
)

# Bloque típico: empieza en el lead del CMP y acaba en el cierre habitual.
_CMP_BLOCK = re.compile(
    r"(?is)"
    r"Utilizamos\s+cookies\s+en\s+nuestro\s+sitio\s+web"
    r".{0,1200}?"
    r"(?:"
    r"Ajustes\s+de\s+Cookie\.?"
    r"|pol[ií]tica\s+de\s+privacidad[^\n\r]*"
    r"|https?://[^\s\)\]]*?politica-de-privacidad[^\s\)\]]*"
    r"|\]\([^\)]*politica-de-privacidad[^\)]*\)"
    r")"
)

_MD_PRIVACY = re.compile(
    r"(?is)\[([^\]]*(?:pol[ií]tica\s+de\s+privacidad|proveedores)[^\]]*)\]"
    r"\((https?://[^\)]*politica-de-privacidad[^\)]*)\)"
)

_HTML_TAG = re.compile(r"(?is)<[^>]+>")


def _collapse(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def cookie_marker_score(text: str) -> int:
    return sum(1 for pattern in _STRONG if pattern.search(text))


def is_cookie_consent_text(text: str | None) -> bool:
    """True solo si el texto parece el banner CMP, no una mención genérica."""
    if not text:
        return False
    collapsed = _collapse(unescape(_HTML_TAG.sub(" ", text)))
    if not collapsed:
        return False
    lower = collapsed.casefold()
    if "utilizamos cookies en nuestro sitio web" in lower:
        return cookie_marker_score(collapsed) >= 2
    if "cookie" not in lower:
        return False
    return cookie_marker_score(collapsed) >= 3


def strip_cookie_consent(text: str | None) -> str | None:
    """Elimina bloques de consentimiento CMP; conserva el resto del texto."""
    if text is None:
        return None
    raw = text.replace("\xa0", " ")
    if not raw.strip():
        return None

    plain = _collapse(unescape(_HTML_TAG.sub(" ", raw)))
    if is_cookie_consent_text(plain):
        remainder = _collapse(_CMP_BLOCK.sub(" ", plain))
        remainder = re.sub(r"(?i)\bproveedores\b", " ", remainder)
        remainder = _collapse(remainder)
        if not remainder or is_cookie_consent_text(remainder):
            return None

    working = raw
    had_cmp = bool(_CMP_BLOCK.search(working)) or is_cookie_consent_text(plain)
    if had_cmp:
        working = _MD_PRIVACY.sub(" ", working)
    working = _CMP_BLOCK.sub(" ", working)
    if had_cmp and "<" in working:
        # Tras quitar el texto CMP, descartar cáscaras HTML del banner.
        working = _HTML_TAG.sub(" ", working)
        working = re.sub(r"(?i)\bproveedores\b", " ", working)

    if is_cookie_consent_text(working):
        return None

    cleaned = _collapse(working)
    if not cleaned:
        return None
    if cleaned == _collapse(raw):
        return raw.strip() or None
    return cleaned


def description_needs_cookie_cleanup(description: str | None) -> bool:
    if not description or not description.strip():
        return False
    if is_cookie_consent_text(description):
        return True
    if not _CMP_BLOCK.search(description) and cookie_marker_score(description) < 2:
        return False
    cleaned = strip_cookie_consent(description)
    if cleaned is None:
        return True
    return _collapse(cleaned) != _collapse(description)


def note_contains_cookie_consent(note: str | None) -> bool:
    if not note:
        return False
    # No mirar solo el JSON oculto: el basura aparece en la parte visible.
    visible = note
    if "<!-- gca:concert" in note:
        visible = note.split("<!-- gca:concert", 1)[0]
    if "<!-- gca:meta" in visible:
        visible = visible.split("<!-- gca:meta", 1)[0]
    return bool(_CMP_BLOCK.search(visible)) or is_cookie_consent_text(visible)
