from datetime import date, datetime, time, timezone

from src.config import load_settings
from src.models.classification import ClassificationResult
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.tickets import (
    bookmark_card_url,
    card_urls_match,
    note_has_entradas_link,
    normalize_ticket_url,
    prefer_ticket_url,
)
from src.sources.galicia_en_concierto.detail_parser import concert_from_detail
from src.storage.bookmark_note import build_note, parse_stored_concert
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.ticket_backfill import TicketBackfillService

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
        confidence=0.5,
        reason="ok",
        matched_preferences=[],
        suggested_tags=[],
    )


def test_normalize_keeps_query_params_and_rejects_hash():
    raw = "HTTPS://Tickets.Example/es/venta?utm_source=ig&fbclid=abc&id=42#frag"
    assert (
        normalize_ticket_url(raw)
        == "https://tickets.example/es/venta?utm_source=ig&fbclid=abc&id=42"
    )
    assert normalize_ticket_url("#") is None
    assert normalize_ticket_url("") is None
    assert normalize_ticket_url(None) is None


def test_prefer_keeps_previous_when_incoming_empty():
    previous = "https://entradium.com/es/events/lions-way"
    assert prefer_ticket_url(None, previous) == previous
    assert prefer_ticket_url("", previous) == previous
    assert prefer_ticket_url("#", previous) == previous
    assert prefer_ticket_url("https://NEW.example/t?x=1", previous) == "https://new.example/t?x=1"


def test_note_with_ticket_shows_entradas_link():
    url = "https://entradium.com/es/events/concierto-de-lions-way-en-vigo?ref=src"
    note = build_note(_concert(ticket_url=url), _result(), pending=False)
    assert f"🎫 **[Entradas]({url})**" in note
    assert note_has_entradas_link(note)
    stored = parse_stored_concert(note)
    assert stored is not None
    assert stored.ticket_url == url


def test_note_without_ticket_omits_entradas():
    note = build_note(_concert(ticket_url=None), _result(), pending=False)
    assert "Entradas" not in note.split("<!-- gca:")[0]
    assert not note_has_entradas_link(note)


def test_detail_parser_reads_ticket_and_keeps_query():
    html = """<!DOCTYPE html><html><body>
    <h1 class="entry-title">Banda</h1>
    <div class="ai1ec-hidden dt-start">2026-09-25T22:00:00+02:00</div>
    <div class="ai1ec-hidden dt-end">2026-09-25T22:15:00+02:00</div>
    <div class="p-location">Sala X, Vigo</div>
    <a class="ai1ec-tickets" href="https://tickets.example/e/1?utm_campaign=fall&keep=1">Entradas</a>
    </body></html>"""
    discovered = DiscoveredEvent(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/banda/",
        detail_url="https://galiciaenconcierto.com/evento/banda/",
        title="Banda",
        scraped_at=NOW,
        ticket_url="https://old.example/generic",
    )
    concert = concert_from_detail(html, discovered, scraped_at=NOW)
    assert (
        concert.ticket_url
        == "https://tickets.example/e/1?utm_campaign=fall&keep=1"
    )


def test_detail_parser_preserves_discovered_when_detail_has_no_ticket():
    html = """<!DOCTYPE html><html><body>
    <h1 class="entry-title">Banda</h1>
    <div class="ai1ec-hidden dt-start">2026-09-25T22:00:00+02:00</div>
    <div class="ai1ec-hidden dt-end">2026-09-25T22:15:00+02:00</div>
    <div class="p-location">Vigo</div>
    <a class="ai1ec-tickets" href="#">Entradas</a>
    </body></html>"""
    discovered = DiscoveredEvent(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/banda/",
        detail_url="https://galiciaenconcierto.com/evento/banda/",
        title="Banda",
        scraped_at=NOW,
        ticket_url="https://listing.example/event/42?utm_source=agenda",
    )
    concert = concert_from_detail(html, discovered, scraped_at=NOW)
    assert concert.ticket_url == "https://listing.example/event/42?utm_source=agenda"


def test_bookmark_card_url_prefers_ticket_else_source():
    source = "https://galiciaenconcierto.com/evento/lions-way/"
    ticket = "https://entradium.com/es/events/concierto-de-lions-way-en-vigo?x=1"
    assert bookmark_card_url(source_url=source, ticket_url=ticket) == ticket
    assert bookmark_card_url(source_url=source, ticket_url=None) == source
    assert bookmark_card_url(source_url=source, ticket_url="#") == source
    assert card_urls_match(ticket, ticket)
    assert not card_urls_match(source, ticket)


class MemoryRepo:
    def __init__(self, bookmarks=None):
        self.bookmarks = {b.url: b for b in bookmarks or []}
        self.writes = 0
        self.link_patches: list[str] = []

    def index(self, *, create_missing: bool = True):
        return dict(self.bookmarks)

    def update(self, bookmark, *, title, note, tags):
        self.writes += 1
        bookmark.title = title
        bookmark.note = note

    def set_link_url(self, bookmark, link_url, *, refresh_banner: bool = False, **_kwargs):
        self.writes += 1
        self.link_patches.append(link_url)
        bookmark.card_url = link_url
        return "updated"


def test_ticket_backfill_updates_card_url_and_note():
    concert = _concert(
        ticket_url="https://entradium.com/es/events/concierto-de-lions-way-en-vigo"
    )
    modern = build_note(concert, _result(), pending=False)
    old_note = modern.replace(
        "🎫 **[Entradas](https://entradium.com/es/events/concierto-de-lions-way-en-vigo)**\n",
        "",
        1,
    )
    bookmark = KnownBookmark(
        id="b1",
        url=concert.source_url,
        title=concert.title,
        note=old_note,
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"maybe", "geo_vigo"},
        card_url=concert.source_url,
    )
    repo = MemoryRepo([bookmark])
    stats = TicketBackfillService(repo=repo, settings=load_settings()).run(dry_run=True)
    assert stats.would_update == 1
    assert repo.writes == 0
    assert bookmark.card_url == concert.source_url

    stats2 = TicketBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats2.updated == 1
    assert repo.writes >= 1
    assert bookmark.card_url == concert.ticket_url
    assert note_has_entradas_link(bookmark.note)
    assert bookmark.list_keys == {"maybe", "geo_vigo"}
    assert repo.link_patches == [concert.ticket_url]

    stats3 = TicketBackfillService(repo=repo, settings=load_settings()).run(dry_run=False)
    assert stats3.noop == 1
