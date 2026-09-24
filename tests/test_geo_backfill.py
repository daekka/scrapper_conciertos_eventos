from datetime import date, datetime, time, timezone

from src.config import load_settings
from src.normalize.geo import GEO_ACORUNA, GEO_LIST_KEYS, GEO_OTHER, GEO_VIGO
from src.storage.bookmark_note import build_note
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.geo_backfill import GeoBackfillService, is_agent_managed
from src.models.discovered import Concert
from src.models.classification import ClassificationResult


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _concert(city: str | None, **kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="X",
        city=city,
        date=date(2026, 12, 1),
        scraped_at=NOW,
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
    )


class MemoryRepo:
    def __init__(self, bookmarks=None):
        self.bookmarks = {b.url: b for b in bookmarks or []}
        self.mutations: list[str] = []
        self.writes = 0

    def index(self, *, create_missing: bool = True):
        return dict(self.bookmarks)

    def assign_list(self, bookmark, list_key):
        self.mutations.append(f"assign:{list_key}")
        self.writes += 1
        bookmark.list_keys.add(list_key)

    def remove_from_list(self, bookmark, list_key):
        self.mutations.append(f"remove:{list_key}")
        self.writes += 1
        bookmark.list_keys.discard(list_key)

    def sync_geo_list(self, bookmark, geo_key):
        managed = bookmark.list_keys & GEO_LIST_KEYS
        if managed == {geo_key}:
            return "noop"
        for old in sorted(managed - {geo_key}):
            self.remove_from_list(bookmark, old)
        if geo_key not in bookmark.list_keys:
            self.assign_list(bookmark, geo_key)
            return "moved" if managed else "added"
        return "moved"


def test_is_agent_managed_requires_gca_markers():
    note = build_note(_concert("Vigo"), _result(), pending=False)
    assert is_agent_managed(
        KnownBookmark(id="1", url="u", title="t", note=note, list_keys={"interested"})
    )
    assert not is_agent_managed(
        KnownBookmark(id="2", url="u2", title="t", note="nota humana", list_keys={"interested"})
    )


def test_backfill_dry_run_no_writes_and_preserves_affinity():
    concert = _concert("A Coruña")
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"interested"},  # decisión humana/actual de afinidad
    )
    repo = MemoryRepo([bookmark])
    stats = GeoBackfillService(repo=repo, settings=load_settings()).run(dry_run=True)
    assert stats.managed == 1
    assert stats.would_add == 1
    assert stats.distribution[GEO_ACORUNA] == 1
    assert repo.writes == 0
    assert bookmark.list_keys == {"interested"}


def test_backfill_moves_wrong_geo_keeps_past():
    concert = _concert("Vigo")
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=note,
        tags=[],
        list_keys={"past", GEO_OTHER},
    )
    repo = MemoryRepo([bookmark])
    stats = GeoBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.added == 1
    assert stats.removed == 1
    assert bookmark.list_keys == {"past", GEO_VIGO}
    assert "remove:geo_other" in repo.mutations
    assert "assign:geo_vigo" in repo.mutations


def test_backfill_idempotent_noop():
    concert = _concert("Ferrol")
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title="t",
        note=note,
        tags=[],
        list_keys={"maybe", "geo_ferrol"},
    )
    repo = MemoryRepo([bookmark])
    stats = GeoBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.noop == 1
    assert repo.writes == 0
    assert bookmark.list_keys == {"maybe", "geo_ferrol"}


def test_backfill_skips_non_agent_bookmarks():
    bookmark = KnownBookmark(
        id="human",
        url="https://example.com/x/",
        title="Manual",
        note="sin marcadores gca",
        tags=[],
        list_keys={"interested"},
    )
    repo = MemoryRepo([bookmark])
    stats = GeoBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.skipped_not_agent == 1
    assert stats.managed == 0
    assert bookmark.list_keys == {"interested"}
