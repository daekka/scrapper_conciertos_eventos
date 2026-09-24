from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from src.normalize.geo import GEO_LIST_KEYS, GEO_LIST_ORDER, geo_list_key_for_concert
from src.storage.bookmark_note import parse_stored_concert
from src.storage.karakeep import KaraKeepClient
from src.storage.models import KnownBookmark

logger = logging.getLogger(__name__)

_AFFINITY = frozenset({"interested", "maybe", "ignored", "past"})


@dataclass
class GeoBackfillStats:
    examined: int = 0
    managed: int = 0
    skipped_not_agent: int = 0
    skipped_no_concert: int = 0
    noop: int = 0
    would_add: int = 0
    would_remove: int = 0
    added: int = 0
    removed: int = 0
    errors: int = 0
    distribution: Counter = field(default_factory=Counter)


def is_agent_managed(bookmark: KnownBookmark) -> bool:
    note = bookmark.note or ""
    return "<!-- gca:concert" in note or "<!-- gca:meta" in note


class GeoBackfillService:
    def __init__(self, *, repo: KaraKeepClient, settings) -> None:
        self.repo = repo
        self.settings = settings

    def run(self, *, dry_run: bool = True) -> GeoBackfillStats:
        stats = GeoBackfillStats()
        index = self.repo.index(create_missing=not dry_run)
        stats.examined = len(index)
        for bookmark in index.values():
            try:
                self._process(bookmark, stats, dry_run=dry_run)
            except Exception as exc:
                stats.errors += 1
                logger.error("Backfill geo falló en %s: %s", bookmark.id, exc)
        self._log_summary(stats, dry_run=dry_run)
        return stats

    def _process(self, bookmark: KnownBookmark, stats: GeoBackfillStats, *, dry_run: bool) -> None:
        if not (bookmark.list_keys & (_AFFINITY | GEO_LIST_KEYS)):
            return
        if not is_agent_managed(bookmark):
            stats.skipped_not_agent += 1
            return
        concert = parse_stored_concert(bookmark.note)
        if concert is None:
            stats.skipped_no_concert += 1
            logger.warning("Bookmark agente sin gca:concert; se omite geo: %s", bookmark.id)
            return
        stats.managed += 1
        geo_key = geo_list_key_for_concert(concert)
        stats.distribution[geo_key] += 1
        managed = bookmark.list_keys & GEO_LIST_KEYS
        if managed == {geo_key}:
            stats.noop += 1
            return
        to_remove = managed - {geo_key}
        needs_add = geo_key not in bookmark.list_keys
        geo_name = self.settings.geo_lists.get(geo_key, geo_key)
        if dry_run:
            stats.would_remove += len(to_remove)
            if needs_add:
                stats.would_add += 1
            for old in sorted(to_remove):
                logger.info(
                    "[DRY-RUN] Quitaría %s de %s",
                    bookmark.url,
                    self.settings.geo_lists.get(old, old),
                )
            if needs_add:
                logger.info("[DRY-RUN] Añadiría %s a %s", bookmark.url, geo_name)
            return
        remove_count = len(to_remove)
        action = self.repo.sync_geo_list(bookmark, geo_key)
        if action == "noop":
            stats.noop += 1
            return
        stats.removed += remove_count
        if needs_add or action in {"added", "moved"}:
            stats.added += 1
        logger.info("Geo backfill %s -> %s (%s)", bookmark.url, geo_name, action)

    def _log_summary(self, stats: GeoBackfillStats, *, dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info(
            "[%s] Geo backfill: examinados=%s gestionados=%s no_agente=%s sin_concert=%s "
            "sin_cambios=%s altas=%s bajas=%s errores=%s",
            mode,
            stats.examined,
            stats.managed,
            stats.skipped_not_agent,
            stats.skipped_no_concert,
            stats.noop,
            stats.would_add if dry_run else stats.added,
            stats.would_remove if dry_run else stats.removed,
            stats.errors,
        )
        for key in GEO_LIST_ORDER:
            name = self.settings.geo_lists.get(key, key)
            logger.info("[%s] %s: %s", mode, name, stats.distribution.get(key, 0))
