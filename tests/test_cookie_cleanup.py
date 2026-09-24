from datetime import date, datetime, timezone

from src.config import load_settings
from src.models.classification import ClassificationResult
from src.models.discovered import Concert
from src.normalize.geo import GEO_VIGO
from src.storage.bookmark_note import build_note, parse_stored_concert
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.cookie_cleanup import CookieCleanupService

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

CMP = (
    'Utilizamos cookies en nuestro sitio web para darle la experiencia más relevante '
    'recordando sus preferencias y visitas repetidas. Al hacer clic en "Aceptar", usted '
    "acepta el uso de TODAS las cookies. Es posible que algunos de los proveedores y Google "
    "traten tus datos personales en virtud de un interés legítimo, algo a lo que puedes "
    "oponerte gestionando los Ajustes de Cookie."
)


def _concert(description=None, **kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="X",
        city="Vigo",
        date=date(2026, 12, 1),
        scraped_at=NOW,
        description=description,
    )
    data.update(kwargs)
    return Concert(**data)


def _result():
    return ClassificationResult(
        classification="INTERESTED",
        confidence=0.9,
        reason="ok",
        matched_preferences=[],
        suggested_tags=[],
        music_genres=[],
    )


class MemoryRepo:
    def __init__(self, bookmarks=None):
        self.bookmarks = {b.url: b for b in bookmarks or []}
        self.writes = 0
        self.mutations: list[str] = []

    def index(self, *, create_missing: bool = True):
        return dict(self.bookmarks)

    def update(self, bookmark, *, title, note, tags):
        self.writes += 1
        self.mutations.append("update")
        bookmark.title = title
        bookmark.note = note


def test_cleanup_detects_and_dry_run_writes_nothing():
    concert = _concert(description="Buen tributo en vivo.")
    note = build_note(concert, _result(), pending=False)
    # Simula nota antigua con CMP en la descripción visible y en gca:concert.
    dirty_note = note.replace("Buen tributo en vivo.", CMP, 1)
    dirty_note = dirty_note.replace(
        '"description":"Buen tributo en vivo."',
        f'"description":{__import__("json").dumps(CMP, ensure_ascii=False)}',
        1,
    )
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=dirty_note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"interested", GEO_VIGO},
    )
    assert "Utilizamos cookies" in bookmark.note
    repo = MemoryRepo([bookmark])
    stats = CookieCleanupService(repo=repo, settings=load_settings()).run(dry_run=True)
    assert stats.detected == 1
    assert stats.would_update == 1
    assert repo.writes == 0
    assert bookmark.list_keys == {"interested", GEO_VIGO}
    assert "Utilizamos cookies" in bookmark.note


def test_cleanup_apply_removes_cookies_preserves_lists_and_is_idempotent():
    concert = _concert(description="Escena local.", genres=["rock"])
    note = build_note(concert, _result(), pending=False)
    dirty_note = note.replace("Escena local.", CMP, 1)
    dirty_note = dirty_note.replace(
        '"description":"Escena local."',
        f'"description":{__import__("json").dumps(CMP, ensure_ascii=False)}',
        1,
    )
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=dirty_note,
        tags=[BookmarkTag(name="concert", attached_by="human")],
        list_keys={"maybe", GEO_VIGO},
    )
    repo = MemoryRepo([bookmark])
    stats = CookieCleanupService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.updated == 1
    assert repo.writes == 1
    assert bookmark.list_keys == {"maybe", GEO_VIGO}
    assert "Utilizamos cookies" not in bookmark.note
    assert "Ajustes de Cookie" not in bookmark.note
    stored = parse_stored_concert(bookmark.note)
    assert stored is not None
    assert stored.description is None
    assert stored.genres == ["rock"]
    assert "🎸 **Género:** Rock" in bookmark.note

    stats2 = CookieCleanupService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats2.noop == 1
    assert stats2.updated == 0
    assert repo.writes == 1


def test_cleanup_noop_on_clean_bookmark():
    concert = _concert(description="Concierto de indie rock en sala pequeña.")
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title="t",
        note=note,
        tags=[],
        list_keys={"interested"},
    )
    repo = MemoryRepo([bookmark])
    stats = CookieCleanupService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.noop == 1
    assert repo.writes == 0


def test_cleanup_skips_non_agent_and_never_calls_llm():
    bookmark = KnownBookmark(
        id="h",
        url="https://example.com/x/",
        title="Manual",
        note=f"nota humana\n{CMP}",
        tags=[],
        list_keys={"interested"},
    )
    repo = MemoryRepo([bookmark])
    stats = CookieCleanupService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.skipped_not_agent == 1
    assert repo.writes == 0
