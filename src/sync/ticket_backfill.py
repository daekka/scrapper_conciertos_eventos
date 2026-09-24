from __future__ import annotations

import logging
from dataclasses import dataclass

from src.normalize.concert_datetime import bookmark_title
from src.normalize.geo import GEO_LIST_KEYS
from src.normalize.tickets import (
    bookmark_card_url,
    card_urls_match,
    note_has_entradas_link,
    prefer_ticket_url,
)
from src.storage.bookmark_note import (
    build_note,
    extract_analysis,
    parse_meta,
    parse_stored_concert,
)
from src.storage.karakeep import KaraKeepClient
from src.storage.models import KnownBookmark

logger = logging.getLogger(__name__)

_AFFINITY = frozenset({"interested", "maybe", "ignored", "past"})


@dataclass
class TicketBackfillStats:
    examined: int = 0
    managed: int = 0
    skipped_not_agent: int = 0
    skipped_no_concert: int = 0
    with_ticket: int = 0
    without_ticket: int = 0
    would_update: int = 0
    updated: int = 0
    noop: int = 0
    errors: int = 0


def is_agent_managed(bookmark: KnownBookmark) -> bool:
    note = bookmark.note or ""
    return "<!-- gca:concert" in note or "<!-- gca:meta" in note


class TicketBackfillService:
    """Alinea URL de tarjeta (+ enlace en nota) con ticket_url. Sin LLM."""

    def __init__(self, *, repo: KaraKeepClient, settings) -> None:
        self.repo = repo
        self.settings = settings

    def run(self, *, dry_run: bool = True) -> TicketBackfillStats:
        stats = TicketBackfillStats()
        index = self.repo.index(create_missing=False)
        stats.examined = len(index)
        for bookmark in index.values():
            try:
                self._process(bookmark, stats, dry_run=dry_run)
            except Exception as exc:
                stats.errors += 1
                logger.error("Ticket backfill falló en %s: %s", bookmark.id, exc)
        self._log_summary(stats, dry_run=dry_run)
        return stats

    def _process(self, bookmark: KnownBookmark, stats: TicketBackfillStats, *, dry_run: bool) -> None:
        if not (bookmark.list_keys & (_AFFINITY | GEO_LIST_KEYS)):
            return
        if not is_agent_managed(bookmark):
            stats.skipped_not_agent += 1
            return
        concert = parse_stored_concert(bookmark.note)
        if concert is None:
            stats.skipped_no_concert += 1
            return
        stats.managed += 1
        concert.ticket_url = prefer_ticket_url(concert.ticket_url, concert.ticket_url)
        if concert.ticket_url:
            stats.with_ticket += 1
        else:
            stats.without_ticket += 1

        desired_card = bookmark_card_url(
            source_url=concert.source_url, ticket_url=concert.ticket_url
        )
        desired_title = bookmark_title(concert)
        current_card = bookmark.card_url or bookmark.url
        card_ok = card_urls_match(current_card, desired_card)
        title_ok = (bookmark.title or "") == desired_title
        has_link = note_has_entradas_link(bookmark.note)
        ticket = concert.ticket_url
        note_ok = (bool(ticket) and has_link and f"[Entradas]({ticket})" in (bookmark.note or "")) or (
            not ticket and not has_link
        )
        if card_ok and note_ok and title_ok:
            stats.noop += 1
            return

        meta = parse_meta(bookmark.note)
        preserved = extract_analysis(bookmark.note)
        new_note = build_note(
            concert,
            None,
            pending=bool(meta.get("pending")),
            preserved_analysis=preserved,
            classification_name=meta.get("classification"),
        )
        if dry_run:
            stats.would_update += 1
            logger.info(
                "[DRY-RUN] %s:\n  tarjeta actual: %s\n  tarjeta nueva: %s\n  título: %s\n  ticket_url: %s",
                bookmark.title or bookmark.url,
                current_card,
                desired_card,
                desired_title,
                ticket or "(ninguna → ficha Galicia)",
            )
            return

        lists_before = set(bookmark.list_keys)
        tags = [(tag.name, tag.attached_by) for tag in bookmark.tags]
        if new_note != bookmark.note or not title_ok:
            self.repo.update(
                bookmark,
                title=desired_title,
                note=new_note,
                tags=tags,
            )
            bookmark.note = new_note
            bookmark.title = desired_title
        if not card_ok:
            self.repo.set_link_url(
                bookmark,
                desired_card,
                refresh_banner=True,
                ticket_page_url=concert.ticket_url,
            )
        elif concert.ticket_url and hasattr(self.repo, "ensure_banner_after_crawl"):
            self.repo.ensure_banner_after_crawl(
                bookmark.id,
                ticket_page_url=concert.ticket_url,
            )
        bookmark.list_keys = lists_before
        stats.updated += 1
        logger.info(
            "Tarjeta/Entradas sincronizadas: %s -> %s",
            bookmark.url,
            desired_card,
        )

    def _log_summary(self, stats: TicketBackfillStats, *, dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info(
            "[%s] Ticket backfill: examinados=%s gestionados=%s con_url=%s sin_url=%s "
            "a_modificar=%s sin_cambios=%s no_agente=%s sin_concert=%s errores=%s",
            mode,
            stats.examined,
            stats.managed,
            stats.with_ticket,
            stats.without_ticket,
            stats.would_update if dry_run else stats.updated,
            stats.noop,
            stats.skipped_not_agent,
            stats.skipped_no_concert,
            stats.errors,
        )
