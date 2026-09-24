from __future__ import annotations

MAX_MUSIC_GENRES = 3
_MAX_LEN = 40
_MAX_WORDS = 4


def normalize_music_genres(raw: list | None) -> list[str]:
    """Filtra y limita géneros del LLM. Vacío/ausente -> []."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.replace("\xa0", " ").split()).strip(" .-_,;")
        if not cleaned or len(cleaned) > _MAX_LEN:
            continue
        if len(cleaned.split()) > _MAX_WORDS:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= MAX_MUSIC_GENRES:
            break
    return out


def format_genre_label(genre: str) -> str:
    text = genre.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def format_genres_display(genres: list[str] | None) -> str:
    cleaned = normalize_music_genres(list(genres or []))
    if not cleaned:
        return "No determinado"
    return " · ".join(format_genre_label(item) for item in cleaned)
