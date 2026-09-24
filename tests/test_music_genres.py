from datetime import date, datetime, timezone

from src.config import load_settings
from src.models.classification import ClassificationResult
from src.models.discovered import Concert
from src.normalize.genres import format_genres_display, normalize_music_genres
from src.storage.bookmark_note import build_note, parse_stored_concert
from src.storage.lists import tags_for_concert
from src.sync.service import SyncService


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _concert(**kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="X",
        city="Vigo",
        date=date(2026, 12, 1),
        scraped_at=NOW,
    )
    data.update(kwargs)
    return Concert(**data)


def test_normalize_music_genres_limits_and_filters():
    assert normalize_music_genres(None) == []
    assert normalize_music_genres([]) == []
    assert normalize_music_genres(["rock"]) == ["rock"]
    assert normalize_music_genres(["rock", "hard rock", "indie", "extra"]) == [
        "rock",
        "hard rock",
        "indie",
    ]
    assert normalize_music_genres(["esta es una frase demasiado larga para un genero"]) == []


def test_classification_music_genres_optional():
    base = {
        "classification": "INTERESTED",
        "confidence": 0.9,
        "reason": "ok",
        "matched_preferences": [],
        "suggested_tags": [],
    }
    assert ClassificationResult.model_validate(base).music_genres == []
    one = ClassificationResult.model_validate({**base, "music_genres": ["rock"]})
    assert one.music_genres == ["rock"]
    many = ClassificationResult.model_validate(
        {**base, "music_genres": ["indie rock", "indie pop", "folk", "noise"]}
    )
    assert many.music_genres == ["indie rock", "indie pop", "folk"]
    missing = ClassificationResult.model_validate({**base, "music_genres": None})
    assert missing.music_genres == []


def test_note_renders_genres_and_persists():
    concert = _concert(genres=["indie rock", "indie pop"])
    result = ClassificationResult(
        classification="INTERESTED",
        confidence=0.9,
        reason="Encaja.",
        matched_preferences=[],
        suggested_tags=[],
        music_genres=["indie rock", "indie pop"],
    )
    note = build_note(concert, result, pending=False)
    assert "🎸 **Género:** Indie rock · Indie pop" in note
    assert '["indie rock","indie pop"]' not in note.split("<!-- gca:concert")[0]
    stored = parse_stored_concert(note)
    assert stored is not None
    assert stored.genres == ["indie rock", "indie pop"]


def test_note_renders_undetermined_when_empty():
    note = build_note(_concert(genres=[]), None, pending=True)
    assert "🎸 **Género:** No determinado" in note


def test_genre_tags_are_added_without_duplicates():
    settings = load_settings()
    concert = _concert(genres=["hard rock", "Hard Rock", "rock"])
    result = ClassificationResult(
        classification="INTERESTED",
        confidence=0.9,
        reason="ok",
        matched_preferences=[],
        suggested_tags=["rock"],
        music_genres=["hard rock", "rock"],
    )
    SyncService._apply_music_genres(concert, result)
    tags = [name for name, _ in tags_for_concert(concert, settings, result)]
    assert tags.count("hard-rock") == 1
    assert tags.count("rock") == 1
    assert "concert" in tags


def test_format_genres_display():
    assert format_genres_display([]) == "No determinado"
    assert format_genres_display(["synth-pop"]) == "Synth-pop"
