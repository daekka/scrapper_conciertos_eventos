from datetime import date, datetime, time, timezone
from pathlib import Path

from src.config import OCIO_LIST_KEY, load_coruna_settings
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.listing_fingerprint import listing_fingerprint
from src.sources.coruna_gal.detail_parser import concert_from_detail, extract_coruna
from src.sources.coruna_gal.feed import parse_feed_xml
from src.sources.coruna_gal.tipos import infer_tipos, primary_list_key
from src.storage.bookmark_note import build_coruna_note, parse_stored_concert
from src.storage.lists import tags_for_coruna
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.identity import event_key
from src.sync.tipo_service import TipoSyncService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "coruna"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def test_infer_tipos_cine_and_concertos():
    assert infer_tipos("Cine", "Docs do mes") == ["Cine"]
    assert infer_tipos("Música, Concertos", "Recital") == ["Concertos"]
    assert primary_list_key(["Cine", "Familias"]) == "cine"
    assert primary_list_key([]) == "otros"


def test_parse_feed_xml():
    items = parse_feed_xml((FIXTURES / "feed_sample.xml").read_text(encoding="utf-8"))
    assert len(items) == 3
    assert items[0].title.startswith("Proxección")
    assert "Cine" in items[0].tags
    assert items[1].tags == ["Música", "Concertos"]
    assert items[0].image_url and "coruna.gal/IMG" in items[0].image_url


def test_coruna_card_url_no_trailing_slash():
    from src.sync.tipo_service import coruna_card_url

    url = "https://www.coruna.gal/web/gl/evento/x/suceso/123"
    assert coruna_card_url(url) == url
    assert not coruna_card_url(url + "/").endswith("/")


def test_extract_coruna_detail():
    html = (FIXTURES / "detail_cine.html").read_text(encoding="utf-8")
    data = extract_coruna(html)
    assert data["titulo"].startswith("Docs do mes")
    assert data["start_raw"].startswith("2026-09-20")
    assert "Palexco" in data["donde"]
    assert "listado" not in (data.get("titulo") or "").casefold()


def test_concert_from_detail_dates_and_tipos():
    html = (FIXTURES / "detail_cine.html").read_text(encoding="utf-8")
    event = DiscoveredEvent(
        source="coruna_gal",
        source_id="docs-do-mes",
        source_url="https://www.coruna.gal/web/es/ociocultura/evento/docs-do-mes",
        detail_url="https://www.coruna.gal/web/es/ociocultura/evento/docs-do-mes",
        title="Proxección: Docs do mes",
        keywords=["Cine", "VOSE"],
        scraped_at=NOW,
    )
    concert = concert_from_detail(event, html)
    assert concert.date == date(2026, 9, 20)
    assert concert.end_date == date(2026, 9, 27)
    assert concert.start_time == time(18, 0)
    assert concert.categories == ["Cine"]
    assert concert.city == "A Coruña"
    assert concert.free is True
    assert primary_list_key(concert.categories) == "cine"


def test_fingerprint_includes_keywords():
    base = DiscoveredEvent(
        source="coruna_gal",
        source_id="x",
        source_url="https://www.coruna.gal/evento/x",
        detail_url="https://www.coruna.gal/evento/x",
        title="Evento",
        scraped_at=NOW,
    )
    with_tags = base.model_copy(update={"keywords": ["Cine"]})
    assert listing_fingerprint(base) != listing_fingerprint(with_tags)


def test_coruna_note_and_tags():
    settings = load_coruna_settings(ROOT)
    concert = Concert(
        source="coruna_gal",
        source_id="docs",
        source_url="https://www.coruna.gal/web/es/ociocultura/evento/docs",
        title="Docs do mes",
        date=date(2026, 9, 20),
        start_time=time(18, 0),
        city="A Coruña",
        venue="Palexco",
        categories=["Cine"],
        free=True,
        scraped_at=NOW,
        listing_fingerprint="abc",
    )
    note = build_coruna_note(concert, list_key="cine")
    assert "Tipología" in note
    assert "🎸" not in note
    assert "<!-- gca:concert" in note
    stored = parse_stored_concert(note)
    assert stored is not None
    assert stored.categories == ["Cine"]
    tags = {name for name, _ in tags_for_coruna(
        concert, base_tags=settings.base_tags, allow_suggested=settings.allow_suggested
    )}
    assert "ocio" in tags
    assert "acoruna" in tags
    assert "cine" in tags
    assert "gratis" in tags
    assert "concert" not in tags


class MemoryRepo:
    def __init__(self, bookmarks: list[KnownBookmark] | None = None) -> None:
        self.bookmarks = {item.url: item for item in bookmarks or []}
        self.mutations: list[str] = []
        self.indexed_keys: set[str] = set()

    def index(self, *, create_missing: bool = True):
        return dict(self.bookmarks)

    def lookup_url(self, url: str):
        return self.bookmarks.get(event_key(url))

    def create(self, *, url, title, note, tags, list_key, created_at=None, **_kwargs):
        concert = parse_stored_concert(note)
        identity = event_key(concert.source_url) if concert and concert.source_url else event_key(url)
        bookmark = KnownBookmark(
            id=f"id-{len(self.bookmarks)+1}",
            url=identity,
            title=title,
            note=note,
            tags=[BookmarkTag(name=name, attached_by=attached) for name, attached in tags],
            list_keys={list_key} if list_key else set(),
            created_at=created_at,
            card_url=url,
        )
        self.bookmarks[bookmark.url] = bookmark
        self.mutations.append(f"create:{list_key}")
        if _kwargs.get("banner_image_url"):
            self.mutations.append(f"banner:{_kwargs['banner_image_url']}")
        return bookmark

    def update(self, bookmark, *, title, note, tags):
        self.mutations.append("update")
        bookmark.title = title
        bookmark.note = note
        bookmark.tags = [
            BookmarkTag(name=name, attached_by=attached) for name, attached in tags
        ]
        return bookmark

    def move_to_past(self, bookmark, *, active_keys=None):
        self.mutations.append("move_to_past")
        keys = set(active_keys) if active_keys is not None else set()
        bookmark.list_keys -= keys
        bookmark.list_keys.add("past")

    def delete_bookmark(self, bookmark):
        self.mutations.append("delete")
        self.bookmarks.pop(bookmark.url, None)

    def list_bookmarks(self, list_key):
        return [b for b in self.bookmarks.values() if list_key in b.list_keys]

    def assign_list(self, bookmark, list_key):
        self.mutations.append(f"assign_list:{list_key}")
        bookmark.list_keys.add(list_key)

    def remove_from_list(self, bookmark, list_key):
        self.mutations.append(f"remove_from_list:{list_key}")
        bookmark.list_keys.discard(list_key)

    def set_created_at(self, bookmark, created_at):
        bookmark.created_at = created_at
        return "updated"

    def set_link_url(self, bookmark, link_url, **_kwargs):
        bookmark.card_url = link_url
        return "updated"

    def set_description(self, bookmark_id, description):
        return None

    def set_reader_html(self, bookmark_id, html):
        return None


class FakeCorunaSource:
    name = "coruna_gal"

    def __init__(self, events: list[DiscoveredEvent], details: dict[str, Concert]):
        self.events = events
        self.details = details

    def discover(self, *, now):
        return list(self.events)

    def fetch_detail(self, event):
        return self.details[event.source_url]


def test_tipo_sync_creates_in_ocio_list_not_concerts():
    settings = load_coruna_settings(ROOT)
    assert "Conciertos" not in " ".join(settings.all_list_names.values())
    url = "https://www.coruna.gal/web/es/ociocultura/evento/docs-do-mes"
    event = DiscoveredEvent(
        source="coruna_gal",
        source_id="docs-do-mes",
        source_url=url,
        detail_url=url,
        title="Docs do mes",
        keywords=["Cine"],
        scraped_at=NOW,
    )
    concert = Concert(
        source="coruna_gal",
        source_id="docs-do-mes",
        source_url=url,
        title="Docs do mes",
        date=date(2026, 10, 5),
        start_time=time(18, 0),
        city="A Coruña",
        categories=["Cine"],
        scraped_at=NOW,
    )
    repo = MemoryRepo()
    service = TipoSyncService(
        source=FakeCorunaSource([event], {url: concert}),
        repo=repo,
        settings=settings,
    )
    assert service.run(now=NOW) == 0
    assert any(m.startswith("create:ocio") for m in repo.mutations)
    bookmark = next(iter(repo.bookmarks.values()))
    assert "ocio" in bookmark.list_keys
    assert "cine" not in bookmark.list_keys
    assert "interested" not in bookmark.list_keys
    assert "cine" in {t.name for t in bookmark.tags}
    assert "concert" not in {t.name for t in bookmark.tags}


def test_tipo_sync_past_and_purge():
    settings = load_coruna_settings(ROOT)
    url = "https://www.coruna.gal/web/es/ociocultura/evento/viejo"
    past_concert = Concert(
        source="coruna_gal",
        source_id="viejo",
        source_url=url,
        title="Evento viejo",
        date=date(2026, 9, 1),
        start_time=time(20, 0),
        city="A Coruña",
        categories=["Teatro"],
        scraped_at=NOW,
        listing_fingerprint="fp1",
    )
    note = build_coruna_note(past_concert, list_key="ocio")
    # Forzar listing_fp en meta: build_coruna_note usa concert.listing_fingerprint
    bookmark = KnownBookmark(
        id="b1",
        url=event_key(url),
        title="viejo",
        note=note,
        tags=[],
        list_keys={"ocio"},
    )
    # Evento ya past respecto a NOW; discover vacío → solo past/purge sobre índice
    # Ajustar a stale: fin + 7 días < NOW (1+7=8 sep < 23 sep) → purge
    repo = MemoryRepo([bookmark])
    service = TipoSyncService(
        source=FakeCorunaSource([], {}),
        repo=repo,
        settings=settings,
    )
    assert service.run(now=NOW) == 0
    assert "move_to_past" in repo.mutations
    assert "delete" in repo.mutations
    assert repo.bookmarks == {}


def test_load_coruna_settings_isolated_lists():
    settings = load_coruna_settings(ROOT)
    names = set(settings.lists.values())
    assert names == {"Ocio Coruña", "Ocio Coruña · Pasados"}
    assert "Conciertos · Interesan" not in settings.all_list_names.values()
    assert OCIO_LIST_KEY in settings.active_list_keys
    assert settings.active_list_keys == frozenset({OCIO_LIST_KEY})
    assert "past" not in settings.active_list_keys
