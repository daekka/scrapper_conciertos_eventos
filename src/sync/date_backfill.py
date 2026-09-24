from __future__ import annotations

import logging
from dataclasses import dataclass

from src.normalize.concert_datetime import (
    bookmark_title,
    concert_created_at,
    created_at_matches,
    format_created_at_api,
)
from src.normalize.geo import GEO_LIST_KEYS
from src.storage.bookmark_note import parse_stored_concert
from src.storage.karakeep import KaraKeepClient
from src.storage.models import KnownBookmark

logger = logging.getLogger(__name__)

_AFFINITY = frozenset({"interested", "maybe", "ignored", "past"})


@dataclass
class DateBackfillStats:
    examined: int = 0
    managed: int = 0
    skipped_not_agent: int = 0
    skipped_no_concert: int = 0
    skipped_no_date: int = 0
    noop: int = 0
    would_update: int = 0
    updated: int = 0
    errors: int = 0


def is_agent_managed(bookmark: KnownBookmark) -> bool:
    note = bookmark.note or ""
    return "<!-- gca:concert" in note or "<!-- gca:meta" in note


class DateBackfillService:
    """Alinea createdAt con la fecha real del concierto. Sin LLM ni otros cambios."""

    def __init__(self, *, repo: KaraKeepClient, settings) -> None:
        self.repo = repo
        self.settings = settings

    def run(self, *, dry_run: bool = True) -> DateBackfillStats:
        stats = DateBackfillStats()
        index = self.repo.index(create_missing=False)
        stats.examined = len(index)
        for bookmark in index.values():
            try:
                self._process(bookmark, stats, dry_run=dry_run)
            except Exception as exc:
                stats.errors += 1
                logger.error("Date backfill falló en %s: %s", bookmark.id, exc)
        self._log_summary(stats, dry_run=dry_run)
        return stats

    def _process(self, bookmark: KnownBookmark, stats: DateBackfillStats, *, dry_run: bool) -> None:
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
        expected = concert_created_at(concert)
        if expected is None:
            stats.skipped_no_date += 1
            logger.warning("Bookmark sin fecha de concierto; se omite createdAt: %s", bookmark.url)
            return
        desired_title = bookmark_title(concert)
        created_ok = created_at_matches(bookmark.created_at, expected)
        title_ok = (bookmark.title or "") == desired_title
        if created_ok and title_ok:
            stats.noop += 1
            return
        label = bookmark.title or bookmark.url
        local_clock = (
            f"{concert.date.isoformat()} {concert.start_time.strftime('%H:%M')}"
            if concert.start_time
            else f"{concert.date.isoformat()} 12:00"
        )
        tz_name = concert.timezone or "Europe/Madrid"
        logger.info(
            "%s:\n  actual createdAt: %s\n  nuevo createdAt: %s\n  título: %s -> %s\n  concierto: %s %s",
            label,
            bookmark.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if bookmark.created_at else None,
            format_created_at_api(expected).replace(".000Z", "Z"),
            bookmark.title,
            desired_title,
            local_clock,
            tz_name,
        )
        if dry_run:
            stats.would_update += 1
            return
        lists_before = set(bookmark.list_keys)
        tags = [(tag.name, tag.attached_by) for tag in bookmark.tags]
        if not title_ok:
            self.repo.update(
                bookmark,
                title=desired_title,
                note=bookmark.note or "",
                tags=tags,
            )
        if not created_ok:
            action = self.repo.set_created_at(bookmark, expected)
            if action == "noop" and title_ok:
                stats.noop += 1
                return
        bookmark.list_keys = lists_before
        stats.updated += 1

    def _log_summary(self, stats: DateBackfillStats, *, dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info(
            "[%s] Date backfill: examinados=%s gestionados=%s a_cambiar=%s sin_cambios=%s "
            "sin_fecha=%s no_agente=%s sin_concert=%s errores=%s",
            mode,
            stats.examined,
            stats.managed,
            stats.would_update if dry_run else stats.updated,
            stats.noop,
            stats.skipped_no_date,
            stats.skipped_not_agent,
            stats.skipped_no_concert,
            stats.errors,
        )
