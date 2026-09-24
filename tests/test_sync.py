from datetime import date, datetime, time, timezone

from src.config import load_settings
from src.enrichment.pipeline import EnrichmentPipeline
from src.errors import ClassificationInvalid
from src.models.classification import ClassificationResult
from src.models.discovered import Concert, DiscoveredEvent
from src.storage.lists import PENDING_TAG
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.identity import event_key
from src.sync.service import SyncService

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class MemoryRepo:
    def __init__(self, bookmarks: list[KnownBookmark] | None = None) -> None:
        self.bookmarks = {item.url: item for item in bookmarks or []}
        self.lookups = 0
        self.mutations: list[str] = []
        self.create_missing_calls: list[bool] = []

    def index(self, *, create_missing: bool = True):
        self.create_missing_calls.append(create_missing)
        return dict(self.bookmarks)

    def lookup_url(self, url: str):
        self.lookups += 1
        return self.bookmarks.get(event_key(url))

    def create(self, *, url, title, note, tags, list_key, created_at=None):
        from src.storage.bookmark_note import parse_stored_concert
        from src.sync.identity import event_key

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
        self.mutations.append("create")
        if created_at is not None:
            self.mutations.append(f"createdAt:{created_at.isoformat()}")
        self.mutations.append(f"card_url:{url}")
        return bookmark

    def set_created_at(self, bookmark, created_at):
        from src.normalize.concert_datetime import created_at_matches

        if created_at_matches(bookmark.created_at, created_at):
            return "noop"
        self.mutations.append(f"set_created_at:{created_at.isoformat()}")
        bookmark.created_at = created_at
        return "updated"

    def set_link_url(self, bookmark, link_url, *, refresh_banner: bool = False, **_kwargs):
        from src.normalize.tickets import card_urls_match

        if card_urls_match(bookmark.card_url or bookmark.url, link_url):
            return "noop"
        self.mutations.append(f"set_link_url:{link_url}")
        if refresh_banner:
            self.mutations.append("refresh_banner")
        bookmark.card_url = link_url
        return "updated"

    def update(self, bookmark, *, title, note, tags):
        self.mutations.append("update")
        human = [tag for tag in bookmark.tags if tag.attached_by == "human"]
        human_names = {tag.name for tag in human}
        bookmark.title = title
        bookmark.note = note
        bookmark.tags = human + [
            BookmarkTag(name=name, attached_by=attached)
            for name, attached in tags
            if name not in human_names
        ]
        return bookmark

    def move_to_past(self, bookmark):
        self.mutations.append("move_to_past")
        bookmark.list_keys -= {"interested", "maybe", "ignored"}
        bookmark.list_keys.add("past")

    def assign_list(self, bookmark, list_key):
        self.mutations.append("assign_list")
        bookmark.list_keys.add(list_key)

    def remove_from_list(self, bookmark, list_key):
        self.mutations.append("remove_from_list")
        bookmark.list_keys.discard(list_key)

    def sync_geo_list(self, bookmark, geo_key):
        from src.normalize.geo import GEO_LIST_KEYS

        managed = bookmark.list_keys & GEO_LIST_KEYS
        if managed == {geo_key}:
            return "noop"
        for old in sorted(managed - {geo_key}):
            self.remove_from_list(bookmark, old)
        if geo_key not in bookmark.list_keys:
            self.assign_list(bookmark, geo_key)
            return "moved" if managed else "added"
        return "moved"

    def detach_tag(self, bookmark, tag_name):
        self.mutations.append("detach_tag")
        bookmark.tags = [tag for tag in bookmark.tags if tag.name != tag_name]


class FakeSource:
    def __init__(self, events, concerts, fail_ids=None):
        self.events = events
        self.concerts = concerts
        self.fail_ids = set(fail_ids or [])
        self.detail_ids: list[str] = []

    def discover(self, *, now):
        return list(self.events)

    def fetch_detail(self, event):
        self.detail_ids.append(event.source_id)
        if event.source_id in self.fail_ids:
            raise RuntimeError("detail down")
        return self.concerts[event.source_id].model_copy(deep=True)


class FakeClassifier:
    def __init__(self, result=None, invalid=False):
        self.result = result
        self.invalid = invalid
        self.calls = 0

    def classify(self, concert, taste):
        self.calls += 1
        if self.invalid:
            raise ClassificationInvalid("no")
        return self.result


def _event(source_id="10:20", **kwargs) -> DiscoveredEvent:
    data = dict(
        source="galicia_en_concierto",
        event_id="10",
        instance_id="20",
        source_id=source_id,
        source_url=f"https://galiciaenconcierto.com/evento/{source_id.replace(':','-')}/",
        detail_url=f"https://galiciaenconcierto.com/evento/{source_id.replace(':','-')}/?instance_id=20",
        title="Banda",
        venue="Sala",
        city="Vigo",
        date=date(2026, 12, 1),
        start_time=time(21, 0),
        scraped_at=NOW,
    )
    data.update(kwargs)
    return DiscoveredEvent(**data)


def _concert(event: DiscoveredEvent, **kwargs) -> Concert:
    data = dict(
        source=event.source,
        source_id=event.source_id,
        source_url=event.source_url,
        title=event.title,
        artist=event.title,
        date=event.date,
        start_time=event.start_time,
        venue=event.venue,
        city=event.city,
        province="Pontevedra",
        timezone="Europe/Madrid",
        scraped_at=NOW,
        description="Texto de la ficha",
    )
    data.update(kwargs)
    return Concert(**data)


def _service(source, repo, classifier):
    return SyncService(
        source=source,
        repo=repo,
        enrichment=EnrichmentPipeline(),
        classifier_factory=lambda: classifier,
        settings=load_settings(),
        taste="indie",
    )


def _result():
    return ClassificationResult(
        classification="INTERESTED",
        confidence=0.91,
        reason="Encaja.",
        matched_preferences=["indie"],
        suggested_tags=["indie"],
    )


def test_new_event_fetches_detail_once_and_second_run_skips_it():
    event = _event()
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    classifier = FakeClassifier(
        ClassificationResult(
            classification="INTERESTED",
            confidence=0.91,
            reason="Encaja.",
            matched_preferences=["indie"],
            suggested_tags=["indie"],
            music_genres=["indie rock", "indie pop"],
        )
    )
    service = _service(source, repo, classifier)
    assert service.run(now=NOW) == 0
    assert source.detail_ids == [event.source_id]
    assert classifier.calls == 1
    bookmark = repo.bookmarks[event.source_url]
    assert "interested" in bookmark.list_keys
    from src.normalize.concert_datetime import concert_created_at
    from src.normalize.geo import GEO_LIST_KEYS, GEO_VIGO
    from src.storage.bookmark_note import parse_stored_concert

    assert bookmark.list_keys & GEO_LIST_KEYS == {GEO_VIGO}
    assert "🎸 **Género:** Indie rock · Indie pop" in bookmark.note
    stored = parse_stored_concert(bookmark.note)
    assert stored is not None
    assert stored.genres == ["indie rock", "indie pop"]
    assert "indie-rock" in {tag.name for tag in bookmark.tags}
    assert any(m.startswith("createdAt:") for m in repo.mutations)
    assert bookmark.created_at == concert_created_at(stored)
    assert any(m.startswith("card_url:") for m in repo.mutations)
    assert bookmark.card_url == stored.source_url  # sin ticket_url en este fixture
    assert service.run(now=NOW) == 0
    assert source.detail_ids == [event.source_id]
    assert classifier.calls == 1
    assert bookmark.list_keys & GEO_LIST_KEYS == {GEO_VIGO}


def test_listing_change_fetches_detail_without_llm():
    event = _event()
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    classifier = FakeClassifier(_result())
    service = _service(source, repo, classifier)
    service.run(now=NOW)
    event.venue = "Otra sala"
    source.concerts[event.source_id] = _concert(event, venue="Otra sala")
    service.run(now=NOW)
    assert source.detail_ids == [event.source_id, event.source_id]
    assert classifier.calls == 1
    note = repo.bookmarks[event.source_url].note
    assert "Otra sala" in note
    assert "Encaja." in note


def test_invalid_llm_keeps_concert_pending():
    event = _event()
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    service = _service(source, repo, FakeClassifier(invalid=True))
    assert service.run(now=NOW) == 0
    bookmark = repo.bookmarks[event.source_url]
    from src.normalize.geo import GEO_LIST_KEYS

    assert not (bookmark.list_keys & {"interested", "maybe", "ignored", "past"})
    assert len(bookmark.list_keys & GEO_LIST_KEYS) == 1
    assert PENDING_TAG in {tag.name for tag in bookmark.tags}


def test_detail_failure_does_not_stop_the_batch():
    first = _event("1:1", source_url="https://galiciaenconcierto.com/evento/uno/")
    second = _event(
        "2:2",
        event_id="2",
        instance_id="2",
        source_url="https://galiciaenconcierto.com/evento/dos/",
        title="Dos",
    )
    source = FakeSource(
        [first, second],
        {first.source_id: _concert(first), second.source_id: _concert(second)},
        fail_ids={first.source_id},
    )
    # RuntimeError is not caught. Use HttpRequestError.
    from src.http.client import HttpRequestError

    class Boom(FakeSource):
        def fetch_detail(self, event):
            self.detail_ids.append(event.source_id)
            if event.source_id in self.fail_ids:
                raise HttpRequestError("detalle")
            return self.concerts[event.source_id].model_copy(deep=True)

    source = Boom(
        [first, second],
        {first.source_id: _concert(first), second.source_id: _concert(second)},
        fail_ids={first.source_id},
    )
    repo = MemoryRepo()
    assert _service(source, repo, FakeClassifier(_result())).run(now=NOW) == 0
    assert "https://galiciaenconcierto.com/evento/dos/" in repo.bookmarks
    assert "https://galiciaenconcierto.com/evento/uno/" not in repo.bookmarks


def test_geo_correction_without_llm_on_unchanged_event():
    from src.normalize.geo import GEO_OTHER, GEO_VIGO
    from src.normalize.listing_fingerprint import listing_fingerprint
    from src.storage.bookmark_note import build_note

    event = _event()
    concert = _concert(event, listing_fingerprint=listing_fingerprint(event))
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="existing",
        url=event.source_url,
        title=event.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="human")],
        list_keys={"interested", GEO_OTHER},  # afinidad humana + geo incorrecta
    )
    source = FakeSource([event], {event.source_id: concert})
    repo = MemoryRepo([bookmark])
    classifier = FakeClassifier(_result())
    assert _service(source, repo, classifier).run(now=NOW) == 0
    assert classifier.calls == 0
    assert source.detail_ids == []
    assert bookmark.list_keys == {"interested", GEO_VIGO}


def test_past_concert_moves_list_without_deleting():
    from src.normalize.geo import GEO_VIGO
    from src.storage.bookmark_note import build_note

    event = _event(date=date(2026, 1, 2), start_time=time(20, 0))
    concert = _concert(event)
    note = build_note(concert, _result(), pending=False)
    bookmark = KnownBookmark(
        id="old",
        url=event.source_url,
        title=event.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"interested", GEO_VIGO},
    )
    repo = MemoryRepo([bookmark])
    source = FakeSource([], {})
    assert _service(source, repo, FakeClassifier(_result())).run(now=NOW) == 0
    assert bookmark.list_keys == {"past", GEO_VIGO}
    assert bookmark.id == "old"


def test_new_past_concert_skips_classifier():
    event = _event(date=date(2026, 1, 2), start_time=time(20, 0))
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    classifier = FakeClassifier(_result())
    assert _service(source, repo, classifier).run(now=NOW) == 0
    assert source.detail_ids == [event.source_id]
    assert classifier.calls == 0
    bookmark = repo.bookmarks[event.source_url]
    assert "past" in bookmark.list_keys
    assert PENDING_TAG not in {tag.name for tag in bookmark.tags}
    from src.normalize.geo import GEO_LIST_KEYS

    assert len(bookmark.list_keys & GEO_LIST_KEYS) == 1


def _many_events(count: int) -> tuple[list[DiscoveredEvent], dict[str, Concert]]:
    events = []
    for number in range(count):
        event = _event(
            f"{number}:{number}",
            event_id=str(number),
            instance_id=str(number),
            source_url=f"https://galiciaenconcierto.com/evento/e{number}/",
            title=f"Evento {number}",
        )
        events.append(event)
    return events, {event.source_id: _concert(event) for event in events}


def test_limit_processes_at_most_n_events_after_discovery():
    events, concerts = _many_events(8)
    source = FakeSource(events, concerts)
    repo = MemoryRepo()
    assert _service(source, repo, FakeClassifier(_result())).run(now=NOW, limit=5, no_ai=True) == 0
    assert source.detail_ids == [event.source_id for event in events[:5]]
    assert repo.lookups == 5
    assert len(repo.bookmarks) == 5


def test_dry_run_fetches_details_without_writes_or_llm():
    events, concerts = _many_events(8)
    source = FakeSource(events, concerts)
    repo = MemoryRepo()
    classifier = FakeClassifier(_result())
    assert (
        _service(source, repo, classifier).run(now=NOW, dry_run=True, no_ai=True, limit=5) == 0
    )
    assert source.detail_ids == [event.source_id for event in events[:5]]
    assert classifier.calls == 0
    assert repo.mutations == []
    assert repo.bookmarks == {}
    assert repo.lookups == 5


def test_dry_run_with_ai_classifies_but_never_writes():
    event = _event()
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    classifier = FakeClassifier(_result())
    assert _service(source, repo, classifier).run(now=NOW, dry_run=True) == 0
    assert source.detail_ids == [event.source_id]
    assert classifier.calls == 1
    assert repo.mutations == []
    assert repo.bookmarks == {}
    assert repo.create_missing_calls == [False]


def test_dry_run_logs_planned_writes_including_past_move(caplog):
    import logging

    event = _event(date=date(2026, 1, 2), start_time=time(20, 0))
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo()
    classifier = FakeClassifier(_result())
    caplog.set_level(logging.INFO)
    assert _service(source, repo, classifier).run(now=NOW, dry_run=True) == 0
    assert classifier.calls == 0
    assert "[DRY-RUN] Crearía bookmark:" in caplog.text
    assert "Conciertos · Pasados" in caplog.text
    assert "lista geográfica" in caplog.text.lower() or "Añadiría a lista geográfica" in caplog.text
    assert "[DRY-RUN] Tags:" in caplog.text
    assert "se omite clasificación" in caplog.text
    assert repo.mutations == []
    assert repo.bookmarks == {}


def test_dry_run_logs_move_for_existing_past_bookmark(caplog):
    import logging
    from src.storage.bookmark_note import build_note

    event = _event(date=date(2026, 1, 2), start_time=time(20, 0))
    note = build_note(_concert(event), _result(), pending=False)
    bookmark = KnownBookmark(
        id="old",
        url=event.source_url,
        title=event.title,
        note=note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"interested"},
    )
    repo = MemoryRepo([bookmark])
    source = FakeSource([], {})
    caplog.set_level(logging.INFO)
    assert _service(source, repo, FakeClassifier(_result())).run(now=NOW, dry_run=True) == 0
    assert "[DRY-RUN] Movería a pasados:" in caplog.text
    assert repo.mutations == []
    assert bookmark.list_keys == {"interested"}


def test_dry_run_update_does_not_mutate_bookmark():
    event = _event()
    bookmark = KnownBookmark(
        id="existing",
        url=event.source_url,
        title=event.title,
        note="nota previa sin huella",
        tags=[BookmarkTag(name="concert", attached_by="human")],
        list_keys={"interested"},
    )
    source = FakeSource([event], {event.source_id: _concert(event)})
    repo = MemoryRepo([bookmark])
    assert _service(source, repo, FakeClassifier(_result())).run(now=NOW, dry_run=True, no_ai=True) == 0
    assert source.detail_ids == [event.source_id]
    assert repo.mutations == []
    assert bookmark.note == "nota previa sin huella"
    assert bookmark.list_keys == {"interested"}
