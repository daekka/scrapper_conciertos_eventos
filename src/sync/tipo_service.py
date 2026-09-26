"""Sync de ocio/cultura Coruña: listas por tipología, sin LLM ni lookup por ticket."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import CorunaSettings
from src.errors import KaraKeepError, ScrapeError
from src.http.client import HttpRequestError
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.concert_datetime import (
    bookmark_title,
    concert_created_at,
    created_at_matches,
    format_created_at_api,
)
from src.normalize.listing_fingerprint import listing_fingerprint
from src.normalize.reader_content import link_description, reader_html
from src.normalize.urls import canonicalize_url
from src.sources.base import ConcertSource
from src.config import OCIO_LIST_KEY
from src.sources.coruna_gal.tipos import primary_list_key
from src.storage.bookmark_note import build_coruna_note, parse_meta, parse_stored_concert
from src.storage.karakeep import KaraKeepClient
from src.storage.lists import merge_existing_ai_tags, tags_for_coruna
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.past import is_past, is_stale

logger = logging.getLogger(__name__)


def coruna_card_url(source_url: str) -> str:
    """URL de tarjeta Coruña: sin barra final (coruna.gal responde 404 con /)."""
    url = canonicalize_url(source_url, force_trailing_slash=False)
    return url.rstrip("/") or url


@dataclass
class TipoRunStats:
    discovered: int = 0
    selected: int = 0
    new: int = 0
    updated: int = 0
    skipped_unchanged: int = 0
    details_fetched: int = 0
    past: int = 0
    deleted: int = 0
    errors: int = 0


class TipoSyncService:
    """Orquestación discover → detail → write → past → purge para Coruña."""

    def __init__(
        self,
        *,
        source: ConcertSource,
        repo: KaraKeepClient | None,
        settings: CorunaSettings,
    ) -> None:
        self.source = source
        self.repo = repo
        self.settings = settings

    def run(
        self,
        *,
        dry_run: bool = False,
        scrape_only: bool = False,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> int:
        moment = now or datetime.now(timezone.utc)
        started = datetime.now(timezone.utc)
        logger.info("Inicio de sincronización Ocio Coruña")
        try:
            discovered = self.source.discover(now=moment)
        except ScrapeError:
            raise
        except HttpRequestError as exc:
            raise ScrapeError(str(exc)) from exc

        stats = TipoRunStats(discovered=len(discovered))
        logger.info("Eventos Coruña encontrados: %s", stats.discovered)
        if scrape_only:
            self._log_end(stats, started)
            return 0
        if self.repo is None:
            raise KaraKeepError("KaraKeep no está configurado")

        selected = discovered if limit is None else discovered[:limit]
        stats.selected = len(selected)
        if limit is not None:
            logger.info(
                "Límite %s: se procesan %s de %s eventos descubiertos",
                limit,
                len(selected),
                len(discovered),
            )

        if limit is None:
            index = self.repo.index(create_missing=not dry_run)
        else:
            index = {}

        new_events: list[DiscoveredEvent] = []
        changed: list[tuple[DiscoveredEvent, KnownBookmark]] = []
        for event in selected:
            known = index.get(event.source_url)
            if known is None:
                known = self.repo.lookup_url(event.source_url)
                if known is not None:
                    index[known.url] = known
            # Sin lookup por ticket_url: evita colisión con conciertos Galicia.
            if known is None:
                new_events.append(event)
                continue
            if not self._same_listing(event, known):
                changed.append((event, known))
                continue
            stats.skipped_unchanged += 1
            concert = parse_stored_concert(known.note)
            if concert is not None and concert.source == "coruna_gal":
                self._ensure_created_at(known, concert, dry_run=dry_run)
                self._ensure_card_url(known, concert, dry_run=dry_run)
                if "past" not in known.list_keys:
                    self._ensure_ocio_list(known, dry_run=dry_run)

        stats.new = len(new_events)
        logger.info(
            "Seleccionados: %s; nuevos: %s; cambios: %s; sin cambios: %s",
            stats.selected,
            len(new_events),
            len(changed),
            stats.skipped_unchanged,
        )

        watched = list(index.values()) if limit is None else [b for _, b in changed]
        for event in new_events:
            try:
                concert = self._detail(event)
                stats.details_fetched += 1
                if is_stale(concert, moment, self.settings.past_retention_days):
                    logger.info(
                        "Evento caducado (> %s días); no se crea: %s",
                        self.settings.past_retention_days,
                        concert.source_url,
                    )
                    stats.new -= 1
                    continue
                list_key = "past" if is_past(concert, moment) else OCIO_LIST_KEY
                meta_class = (
                    "past"
                    if list_key == "past"
                    else primary_list_key(concert.categories)
                )
                note = build_coruna_note(concert, list_key=meta_class)
                tags = tags_for_coruna(
                    concert,
                    base_tags=self.settings.base_tags,
                    allow_suggested=self.settings.allow_suggested,
                )
                created = self._store_new(
                    dry_run=dry_run,
                    concert=concert,
                    note=note,
                    tags=tags,
                    list_key=list_key,
                )
                if created is not None:
                    self._ensure_created_at(created, concert, dry_run=dry_run)
                    self._ensure_card_url(created, concert, dry_run=dry_run)
                    self._ensure_reader_content(created, concert, dry_run=dry_run)
                    self._ensure_banner(created, concert, dry_run=dry_run)
                    watched.append(created)
            except (HttpRequestError, ScrapeError, KaraKeepError) as exc:
                stats.errors += 1
                logger.error("No se pudo crear %s: %s", event.source_url, exc)
            except Exception as exc:
                stats.errors += 1
                logger.exception("Error inesperado creando %s: %s", event.source_url, exc)

        for event, bookmark in changed:
            try:
                concert = self._detail(event)
                stats.details_fetched += 1
                list_key = "past" if is_past(concert, moment) else OCIO_LIST_KEY
                if "past" in bookmark.list_keys:
                    list_key = "past"
                meta_class = (
                    "past"
                    if list_key == "past"
                    else primary_list_key(concert.categories)
                )
                note = build_coruna_note(concert, list_key=meta_class)
                generated = tags_for_coruna(
                    concert,
                    base_tags=self.settings.base_tags,
                    allow_suggested=self.settings.allow_suggested,
                )
                tags = merge_existing_ai_tags(
                    generated,
                    bookmark,
                    set(self.settings.allow_suggested),
                )
                self._store_update(
                    dry_run=dry_run,
                    bookmark=bookmark,
                    title=bookmark_title(concert),
                    note=note,
                    tags=tags,
                    url=event.source_url,
                )
                if list_key != "past":
                    self._ensure_ocio_list(bookmark, dry_run=dry_run)
                elif list_key == "past" and not dry_run:
                    self.repo.move_to_past(
                        bookmark, active_keys=self.settings.active_list_keys
                    )
                self._ensure_created_at(bookmark, concert, dry_run=dry_run)
                self._ensure_card_url(bookmark, concert, dry_run=dry_run)
                self._ensure_reader_content(bookmark, concert, dry_run=dry_run)
                self._ensure_banner(bookmark, concert, dry_run=dry_run)
                stats.updated += 1
            except (HttpRequestError, ScrapeError, KaraKeepError) as exc:
                stats.errors += 1
                logger.error("No se pudo actualizar %s: %s", event.source_url, exc)
            except Exception as exc:
                stats.errors += 1
                logger.exception("Error inesperado actualizando %s: %s", event.source_url, exc)

        stats.past += self._move_past(watched, moment, dry_run=dry_run)
        stats.deleted += self._purge_stale(
            index=index,
            watched=watched,
            now=moment,
            dry_run=dry_run,
            limit=limit,
        )
        self._log_end(stats, started)
        return 0

    def _detail(self, event: DiscoveredEvent) -> Concert:
        concert = self.source.fetch_detail(event)
        concert.listing_fingerprint = listing_fingerprint(event)
        return concert

    def _store_new(self, *, dry_run: bool, concert: Concert, note: str, tags, list_key: str):
        tag_names = ", ".join(name for name, _ in tags) or "(ninguno)"
        list_name = self.settings.lists.get(list_key, list_key)
        # Tarjeta = ficha Coruña sin barra final (404 con /).
        card_url = coruna_card_url(concert.source_url)
        if dry_run:
            logger.info("[DRY-RUN] Crearía bookmark Coruña: %s", concert.source_url)
            logger.info("[DRY-RUN] URL de tarjeta: %s", card_url)
            if concert.image_url:
                logger.info("[DRY-RUN] Banner desde RSS: %s", concert.image_url)
            else:
                logger.info("[DRY-RUN] Banner por defecto: logo_coruña.png")
            created_at = concert_created_at(concert)
            if created_at is not None:
                logger.info("[DRY-RUN] createdAt: %s", created_at.isoformat())
            logger.info("[DRY-RUN] Añadiría a lista: %s", list_name)
            logger.info("[DRY-RUN] Tags: %s", tag_names)
            return KnownBookmark(
                id=f"dry-run-{concert.source_id}",
                url=concert.source_url,
                title=bookmark_title(concert),
                note=note,
                tags=[BookmarkTag(name=name, attached_by=attached) for name, attached in tags],
                list_keys={list_key},
                created_at=created_at,
                card_url=card_url,
            )
        return self.repo.create(
            url=card_url,
            title=bookmark_title(concert),
            note=note,
            tags=tags,
            list_key=list_key,
            created_at=concert_created_at(concert),
            banner_image_url=concert.image_url,
            use_default_banner=True,
            scrape_ticket_banner=False,
        )

    def _store_update(
        self,
        *,
        dry_run: bool,
        bookmark: KnownBookmark,
        title: str,
        note: str,
        tags,
        url: str,
    ) -> None:
        tag_names = ", ".join(name for name, _ in tags) or "(ninguno)"
        if dry_run:
            logger.info("[DRY-RUN] Actualizaría bookmark Coruña: %s", url)
            logger.info("[DRY-RUN] Tags: %s", tag_names)
            return
        self.repo.update(bookmark, title=title, note=note, tags=tags)

    def _ensure_ocio_list(self, bookmark: KnownBookmark, *, dry_run: bool) -> str:
        """Garantiza que el bookmark esté en «Ocio Coruña» (si no es past)."""
        if "past" in bookmark.list_keys:
            return "noop"
        desired = OCIO_LIST_KEY
        active = self.settings.active_list_keys
        managed = bookmark.list_keys & active
        if managed == {desired}:
            return "noop"
        list_name = self.settings.lists.get(desired, desired)
        if dry_run:
            for old in managed - {desired}:
                logger.info(
                    "[DRY-RUN] Quitaría de lista: %s",
                    self.settings.lists.get(old, old),
                )
            if desired not in managed:
                logger.info("[DRY-RUN] Añadiría a lista: %s", list_name)
            return "moved" if managed else "added"
        for old in sorted(managed - {desired}):
            self.repo.remove_from_list(bookmark, old)
        if desired not in bookmark.list_keys:
            self.repo.assign_list(bookmark, desired)
        logger.info("Lista Ocio Coruña %s -> %s", bookmark.url, list_name)
        return "moved" if managed else "added"

    def _ensure_created_at(self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool) -> str:
        expected = concert_created_at(concert)
        if expected is None:
            return "noop"
        if created_at_matches(bookmark.created_at, expected):
            return "noop"
        if dry_run:
            logger.info(
                "[DRY-RUN] Ajustaría createdAt de %s: %s -> %s",
                bookmark.url,
                bookmark.created_at.isoformat() if bookmark.created_at else None,
                format_created_at_api(expected),
            )
            return "updated"
        action = self.repo.set_created_at(bookmark, expected)
        if action != "noop":
            logger.info(
                "createdAt %s -> %s",
                bookmark.url,
                format_created_at_api(expected),
            )
        return action

    def _ensure_card_url(self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool) -> str:
        desired = coruna_card_url(concert.source_url)
        current = bookmark.card_url or bookmark.url
        # Comparación literal: coruna.gal da 404 con barra final.
        if current == desired:
            return "noop"
        if dry_run:
            logger.info(
                "[DRY-RUN] URL de tarjeta %s: %s -> %s",
                bookmark.url,
                current,
                desired,
            )
            return "updated"
        action = self.repo.set_link_url(bookmark, desired, refresh_banner=False)
        if action != "noop":
            logger.info("URL de tarjeta actualizada %s -> %s", bookmark.url, desired)
        return action

    def _ensure_banner(
        self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool
    ) -> str:
        if bookmark.id.startswith("dry-run-"):
            return "noop"
        if dry_run:
            if concert.image_url:
                logger.info("[DRY-RUN] Banner RSS para %s: %s", bookmark.url, concert.image_url)
            else:
                logger.info("[DRY-RUN] Banner logo Coruña para %s", bookmark.url)
            return "updated"
        if concert.image_url and hasattr(self.repo, "ensure_banner_from_url"):
            ok = self.repo.ensure_banner_from_url(bookmark.id, concert.image_url)
            if ok:
                return "updated"
        if hasattr(self.repo, "ensure_default_banner_after_crawl"):
            self.repo.ensure_default_banner_after_crawl(bookmark.id)
            return "updated"
        if hasattr(self.repo, "_set_default_banner"):
            self.repo._set_default_banner(bookmark.id)
            return "updated"
        return "noop"

    def _ensure_reader_content(
        self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool
    ) -> str:
        if bookmark.id.startswith("dry-run-"):
            return "noop"
        description = link_description(concert)
        html = reader_html(concert)
        if dry_run:
            logger.info("[DRY-RUN] Reader para %s", bookmark.url)
            return "updated"
        if not hasattr(self.repo, "set_description") or not hasattr(self.repo, "set_reader_html"):
            return "noop"
        self.repo.set_description(bookmark.id, description)
        self.repo.set_reader_html(bookmark.id, html)
        return "updated"

    def _move_past(self, bookmarks: list[KnownBookmark], now: datetime, *, dry_run: bool) -> int:
        moved = 0
        seen: set[str] = set()
        active = self.settings.active_list_keys
        for bookmark in bookmarks:
            if bookmark.id in seen:
                continue
            seen.add(bookmark.id)
            if not bookmark.list_keys & active:
                continue
            concert = parse_stored_concert(bookmark.note)
            if concert is None or concert.source != "coruna_gal":
                continue
            if not is_past(concert, now):
                continue
            if dry_run:
                logger.info("[DRY-RUN] Movería a pasados Coruña: %s", bookmark.url)
            else:
                self.repo.move_to_past(bookmark, active_keys=active)
                logger.info("Evento Coruña pasado: %s", bookmark.url)
            moved += 1
        return moved

    def _purge_stale(
        self,
        *,
        index: dict[str, KnownBookmark],
        watched: list[KnownBookmark],
        now: datetime,
        dry_run: bool,
        limit: int | None,
    ) -> int:
        assert self.repo is not None
        candidates: dict[str, KnownBookmark] = {}
        for bookmark in index.values():
            candidates[bookmark.id] = bookmark
        for bookmark in watched:
            candidates[bookmark.id] = bookmark
        if limit is not None:
            try:
                for bookmark in self.repo.list_bookmarks("past"):
                    candidates[bookmark.id] = bookmark
            except KaraKeepError as exc:
                logger.info("Pasados Coruña no disponible para purga: %s", exc)
        deleted = 0
        retention = self.settings.past_retention_days
        for bookmark in list(candidates.values()):
            concert = parse_stored_concert(bookmark.note)
            if concert is None or concert.source != "coruna_gal":
                continue
            if not is_stale(concert, now, retention):
                continue
            if dry_run:
                logger.info("[DRY-RUN] Borraría bookmark Coruña: %s", bookmark.url)
            else:
                try:
                    self.repo.delete_bookmark(bookmark)
                    logger.info("Bookmark Coruña borrado (caducado): %s", bookmark.url)
                except KaraKeepError as exc:
                    logger.error("No se pudo borrar %s: %s", bookmark.url, exc)
                    continue
            deleted += 1
        return deleted

    @staticmethod
    def _same_listing(event: DiscoveredEvent, bookmark: KnownBookmark) -> bool:
        stored = parse_meta(bookmark.note).get("listing_fp")
        return bool(stored) and stored == listing_fingerprint(event)

    @staticmethod
    def _log_end(stats: TipoRunStats, started: datetime) -> None:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info(
            "Fin Coruña: encontrados=%s seleccionados=%s nuevos=%s actualizados=%s "
            "sin_cambios=%s fichas=%s pasados=%s borrados=%s errores=%s duración=%.2fs",
            stats.discovered,
            stats.selected,
            stats.new,
            stats.updated,
            stats.skipped_unchanged,
            stats.details_fetched,
            stats.past,
            stats.deleted,
            stats.errors,
            elapsed,
        )
