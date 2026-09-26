"""Tipologías de ocio/cultura Coruña y mapeo a claves de lista KaraKeep."""

from __future__ import annotations

import re

# Orden = prioridad de lista primaria (primer match gana).
TIPO_PATTERNS: list[tuple[str, str, str]] = [
    # (clave_lista, etiqueta_display, regex)
    ("cine", "Cine", r"\b(?:cine|cinema|proxecci[oó]ns?|pel[ií]cula|vose|docs?\s+do\s+mes)\b"),
    ("teatro", "Teatro", r"\b(?:teatro|teatral|obra\s+de\s+teatro|ciclo\s+principal|sen\s+numerar|todo\s+p[uú]blico)\b"),
    ("concertos", "Concertos", r"\b(?:concertos?|concerto|m[uú]sica|recital)\b"),
    ("danza", "Danza", r"\b(?:danza|baile|ballet|trc\s*danza)\b"),
    ("exposicions", "Exposicións", r"\b(?:exposici[oó]ns?|exposici[oó]n|mostra|fotogr[aá]fica)\b"),
    (
        "cursos",
        "Cursos e talleres",
        r"\b(?:cursos?|talleres?|obradoiros?|masterclass|formaci[oó]n|taller)\b",
    ),
    (
        "conferencias",
        "Conferencias e congresos",
        r"\b(?:conferencias?|congresos?|charla|presentaci[oó]n\s+do\s+libro|encontros?)\b",
    ),
    (
        "deporte",
        "Deporte",
        r"\b(?:deporte|deportes|f[uú]tbol|futbol|voleibol|hockey|carreira|torneo|liga|f\.?\s*s\.?)\b",
    ),
    ("espectaculos", "Espectáculos", r"\b(?:espect[aá]culos?|maxia|circo|humor|mon[oó]logo)\b"),
    (
        "familias",
        "Familias",
        r"\b(?:familias?|nenos|crianzas|bebes?|bebescena|contacontos|cantoconto)\b",
    ),
    ("festas", "Festas", r"\b(?:festas?|festival|feiras?)\b"),
    ("visitas", "Visitas e rutas", r"\b(?:visitas?|rutas?|ando\s+na\s+coru)\b"),
    ("comic", "Cómic", r"\b(?:c[oó]mic|vi[nñ]etas|banda\s+dese[nñ]ada)\b"),
]

OTROS_KEY = "otros"
OTROS_LABEL = "Otros"

TIPO_KEYS: tuple[str, ...] = tuple(key for key, _, _ in TIPO_PATTERNS) + (OTROS_KEY,)

KEY_TO_LABEL: dict[str, str] = {key: label for key, label, _ in TIPO_PATTERNS}
KEY_TO_LABEL[OTROS_KEY] = OTROS_LABEL

LABEL_TO_KEY: dict[str, str] = {label.casefold(): key for key, label, _ in TIPO_PATTERNS}
LABEL_TO_KEY[OTROS_LABEL.casefold()] = OTROS_KEY


def infer_tipos(*texts: str) -> list[str]:
    """Devuelve etiquetas display detectadas (orden de TIPO_PATTERNS), sin duplicados."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return []
    found: list[str] = []
    for _, label, pattern in TIPO_PATTERNS:
        if re.search(pattern, blob, re.I):
            found.append(label)
    return found


def tipo_keys_from_labels(labels: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = LABEL_TO_KEY.get(label.casefold())
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def primary_list_key(labels: list[str]) -> str:
    """Lista KaraKeep primaria: primer tipología detectada, o ``otros``."""
    keys = tipo_keys_from_labels(labels)
    return keys[0] if keys else OTROS_KEY
