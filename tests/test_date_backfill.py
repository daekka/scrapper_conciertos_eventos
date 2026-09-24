from datetime import date, datetime, time, timezone

from src.config import load_settings
from src.models.classification import ClassificationResult
from src.models.discovered import Concert
from src.normalize.concert_datetime import bookmark_title, concert_created_at, format_created_at_api
from src.normalize.geo import GEO_VIGO
from src.storage.bookmark_note import build_note
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.date_backfill import DateBackfillService

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _concert(**kwargs) -> Concert:
    data = dict(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/lions-way/",
        title="Lions Way",
        city="Vigo",
        date=date(2026, 9, 25),
        start_time=time(22, 0),
        timezone="Europe/Madrid",
        scraped_at=NOW,
    )
    data.update(kwargs)
    return Concert(**data)


def _result():
    return ClassificationResult(
        classification="MAYBE",
        confidence=0.55,
        reason="ok",
        matched_preferences=[],
        suggested_tags=[],
    )


class MemoryRepo:
    def __init__(self, bookmarks=None):
        self.bookmarks = {b.url: b for b in bookmarks or []}
        self.patches: list[dict] = []
        self.writes = 0
        self.title_updates = 0

    def index(self, *, create_missing: bool = True):
        return dict(self.bookmarks)

    def update(self, bookmark, *, title, note, tags):
        self.title_updates += 1
        bookmark.title = title
        bookmark.note = note
        return "updated"

    def set_created_at(self, bookmark, created_at):
        self.writes += 1
        self.patches.append({"id": bookmark.id, "createdAt": format_created_at_api(created_at)})
        # Only createdAt — note/tags/lists untouched.
        bookmark.created_at = created_at
        return "updated"


def test_backfill_dry_run_detects_wrong_created_at_without_writes():
    concert = _concert()
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"maybe", GEO_VIGO},
        created_at=datetime(2026, 9, 23, 20, 42, 42, tzinfo=timezone.utc),
    )
    note_before = bookmark.note
    tags_before = list(bookmark.tags)
    lists_before = set(bookmark.list_keys)
    repo = MemoryRepo([bookmark])
    stats = DateBackfillService(repo=repo, settings=load_settings()).run(dry_run=True)
    assert stats.managed == 1
    assert stats.would_update == 1
    assert repo.writes == 0
    assert bookmark.created_at == datetime(2026, 9, 23, 20, 42, 42, tzinfo=timezone.utc)
    assert bookmark.note == note_before
    assert bookmark.tags == tags_before
    assert bookmark.list_keys == lists_before


def test_backfill_apply_patches_only_created_at_and_is_idempotent():
    concert = _concert()
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="human")],
        list_keys={"maybe", GEO_VIGO},
        created_at=datetime(2026, 9, 23, 20, 42, 42, tzinfo=timezone.utc),
    )
    repo = MemoryRepo([bookmark])
    stats = DateBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    expected = concert_created_at(concert)
    assert stats.updated == 1
    assert repo.writes == 1
    assert repo.title_updates == 1
    assert repo.patches == [{"id": "b1", "createdAt": "2026-09-25T20:00:00.000Z"}]
    assert bookmark.created_at == expected
    assert bookmark.title == bookmark_title(concert)
    assert "maybe" in bookmark.list_keys and GEO_VIGO in bookmark.list_keys
    assert bookmark.note == note
    assert bookmark.tags[0].name == "concert"

    stats2 = DateBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats2.noop == 1
    assert stats2.updated == 0
    assert repo.writes == 1
    assert repo.title_updates == 1


def test_backfill_skips_missing_date():
    concert = _concert(date=None, start_time=None)
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title="X",
        note=note,
        tags=[],
        list_keys={"interested"},
        created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    repo = MemoryRepo([bookmark])
    stats = DateBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.skipped_no_date == 1
    assert repo.writes == 0
    assert bookmark.created_at == datetime(2026, 9, 23, tzinfo=timezone.utc)


def test_backfill_skips_non_agent():
    bookmark = KnownBookmark(
        id="h",
        url="https://example.com/x/",
        title="Manual",
        note="sin gca",
        tags=[],
        list_keys={"interested"},
        created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    repo = MemoryRepo([bookmark])
    stats = DateBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats.skipped_not_agent == 1
    assert repo.writes == 0
