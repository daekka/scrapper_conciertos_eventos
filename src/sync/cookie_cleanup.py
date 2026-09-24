from __future__ import annotations

import logging
from dataclasses import dataclass

from src.normalize.cookies import (
    description_needs_cookie_cleanup,
    note_contains_cookie_consent,
    strip_cookie_consent,
)
from src.normalize.geo import GEO_LIST_KEYS
from src.normalize.reader_content import (
    link_description,
    reader_content_needs_refresh,
    reader_html,
)
from src.normalize.ticket_image import fetch_ticket_poster, is_galicia_url
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
class CookieCleanupStats:
    examined: int = 0
    managed: int = 0
    skipped_not_agent: int = 0
    skipped_no_concert: int = 0
    detected: int = 0
    would_update: int = 0
    updated: int = 0
    noop: int = 0
    errors: int = 0


def is_agent_managed(bookmark: KnownBookmark) -> bool:
    note = bookmark.note or ""
    return "<!-- gca:concert" in note or "<!-- gca:meta" in note


def _note_needs_format_refresh(note: str | None) -> bool:
    text = note or ""
    return "**Cuándo:**" not in text


def _banner_needs_ticket_poster(repo, bookmark: KnownBookmark, concert) -> bool:
    ticket = concert.ticket_url
    if not ticket or is_galicia_url(ticket):
        return False
    if not hasattr(repo, "set_banner_image"):
        return False
    if not hasattr(repo, "_get_bookmark"):
        return False
    try:
        payload = repo._get_bookmark(bookmark.id)
    except Exception:
        return True
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("assetType") != "bannerImage":
            continue
        name = (asset.get("fileName") or "").lower()
        if name in {"", "concert-default.png"} or name.startswith("concert-default"):
            return True
        return False
    return True


class CookieCleanupService:
    """Limpia CMP de cookies en notas/reader y refresca Cuándo/Dónde/Precio. Sin LLM."""

    def __init__(self, *, repo: KaraKeepClient, settings) -> None:
        self.repo = repo
        self.settings = settings

    def run(self, *, dry_run: bool = True) -> CookieCleanupStats:
        stats = CookieCleanupStats()
        index = self.repo.index(create_missing=False)
        stats.examined = len(index)
        for bookmark in index.values():
            try:
                self._process(bookmark, stats, dry_run=dry_run)
            except Exception as exc:
                stats.errors += 1
                logger.error("Cookie cleanup falló en %s: %s", bookmark.id, exc)
        self._log_summary(stats, dry_run=dry_run)
        return stats

    def _process(self, bookmark: KnownBookmark, stats: CookieCleanupStats, *, dry_run: bool) -> None:
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
        dirty_desc = description_needs_cookie_cleanup(concert.description)
        dirty_note = note_contains_cookie_consent(bookmark.note)
        format_stale = _note_needs_format_refresh(bookmark.note)
        reader_text = ""
        if hasattr(self.repo, "get_readable_content"):
            try:
                reader_text = self.repo.get_readable_content(bookmark.id)
            except Exception as exc:
                logger.warning("No se pudo leer reader de %s: %s", bookmark.id, exc)
        dirty_reader = reader_content_needs_refresh(reader_text)
        needs_banner = _banner_needs_ticket_poster(self.repo, bookmark, concert)
        if (
            not dirty_desc
            and not dirty_note
            and not format_stale
            and not dirty_reader
            and not needs_banner
        ):
            stats.noop += 1
            return
        stats.detected += 1
        concert.description = strip_cookie_consent(concert.description)
        meta = parse_meta(bookmark.note)
        preserved = extract_analysis(bookmark.note)
        new_note = build_note(
            concert,
            None,
            pending=bool(meta.get("pending")),
            preserved_analysis=preserved,
            classification_name=meta.get("classification"),
        )
        description = link_description(concert)
        html = reader_html(concert)
        if dry_run:
            stats.would_update += 1
            logger.info(
                "[DRY-RUN] Limpiaría cookies/formato/banner en %s "
                "(nota=%s reader=%s banner=%s)",
                bookmark.url,
                dirty_desc or dirty_note or format_stale,
                dirty_reader,
                needs_banner,
            )
            return
        affinity = set(bookmark.list_keys)
        tags = [(tag.name, tag.attached_by) for tag in bookmark.tags]
        if new_note != bookmark.note:
            self.repo.update(
                bookmark,
                title=bookmark.title or concert.title,
                note=new_note,
                tags=tags,
            )
            bookmark.note = new_note
        if hasattr(self.repo, "set_description"):
            self.repo.set_description(bookmark.id, description)
        if hasattr(self.repo, "set_reader_html"):
            self.repo.set_reader_html(bookmark.id, html)
        if needs_banner and hasattr(self.repo, "http"):
            poster = fetch_ticket_poster(self.repo.http, concert.ticket_url)
            if poster is not None:
                raw, filename, content_type = poster
                self.repo.set_banner_image(
                    bookmark.id,
                    raw,
                    filename=filename,
                    content_type=content_type,
                )
                logger.info("Banner de entradas: %s (%s)", bookmark.url, filename)
        bookmark.list_keys = affinity
        stats.updated += 1
        logger.info("Cookies/formato actualizados: %s", bookmark.url)

    def _log_summary(self, stats: CookieCleanupStats, *, dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info(
            "[%s] Cookie cleanup: examinados=%s gestionados=%s detectados=%s "
            "a_modificar=%s sin_cambios=%s no_agente=%s sin_concert=%s errores=%s",
            mode,
            stats.examined,
            stats.managed,
            stats.detected,
            stats.would_update if dry_run else stats.updated,
            stats.noop,
            stats.skipped_not_agent,
            stats.skipped_no_concert,
            stats.errors,
        )
