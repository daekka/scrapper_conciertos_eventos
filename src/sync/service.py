from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.enrichment.pipeline import EnrichmentPipeline
from src.errors import ClassificationInvalid, KaraKeepError, LLMError, ScrapeError
from src.http.client import HttpRequestError
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.tickets import bookmark_card_url, card_urls_match, prefer_ticket_url
from src.normalize.concert_datetime import (
    bookmark_title,
    concert_created_at,
    created_at_matches,
    format_created_at_api,
)
from src.normalize.geo import GEO_LIST_KEYS, geo_list_key_for_concert
from src.normalize.genres import normalize_music_genres
from src.normalize.listing_fingerprint import listing_fingerprint
from src.normalize.reader_content import link_description, reader_html
from src.normalize.ticket_image import fetch_ticket_poster, is_galicia_url
from src.sources.base import ConcertSource
from src.storage.bookmark_note import (
    build_note,
    extract_analysis,
    parse_meta,
    parse_stored_concert,
)
from src.storage.karakeep import KaraKeepClient
from src.storage.lists import PENDING_TAG, merge_existing_ai_tags, tags_for_concert
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.past import is_past, is_stale

logger = logging.getLogger(__name__)

_LIST_FOR = {
    "INTERESTED": "interested",
    "MAYBE": "maybe",
    "IGNORE": "ignored",
}
_ACTIVE = {"interested", "maybe", "ignored"}


@dataclass
class RunStats:
    discovered: int = 0
    selected: int = 0
    new: int = 0
    updated: int = 0
    classified: int = 0
    ignored: int = 0
    skipped_unchanged: int = 0
    details_fetched: int = 0
    past: int = 0
    deleted: int = 0
    errors: int = 0
    pending: int = 0
    llm_transport_failures: int = 0
    llm_attempts: int = 0


class SyncService:
    def __init__(
        self,
        *,
        source: ConcertSource,
        repo: KaraKeepClient | None,
        enrichment: EnrichmentPipeline,
        classifier_factory,
        settings,
        taste: str,
    ) -> None:
        self.source = source
        self.repo = repo
        self.enrichment = enrichment
        self.classifier_factory = classifier_factory
        self.settings = settings
        self.taste = taste
        self._classifier = None

    def run(
        self,
        *,
        dry_run: bool = False,
        scrape_only: bool = False,
        no_ai: bool = False,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> int:
        moment = now or datetime.now(timezone.utc)
        started = datetime.now(timezone.utc)
        logger.info("Inicio de sincronización")
        try:
            discovered = self.source.discover(now=moment)
        except ScrapeError:
            raise
        except HttpRequestError as exc:
            raise ScrapeError(str(exc)) from exc
        stats = RunStats(discovered=len(discovered))
        logger.info("Conciertos encontrados: %s", stats.discovered)
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
        pending: list[KnownBookmark] = []
        for event in selected:
            known = index.get(event.source_url)
            if known is None:
                known = self.repo.lookup_url(event.source_url)
                if known is not None:
                    index[known.url] = known
            if known is None and event.ticket_url:
                from src.normalize.tickets import normalize_ticket_url

                ticket = normalize_ticket_url(event.ticket_url)
                if ticket:
                    known = self.repo.lookup_url(ticket)
                    if known is not None:
                        index[known.url] = known
            if known is None:
                new_events.append(event)
                continue
            if not self._same_listing(event, known):
                changed.append((event, known))
                continue
            if self._needs_classification(known):
                pending.append(known)
                continue
            stats.skipped_unchanged += 1
            concert = parse_stored_concert(known.note)
            if concert is not None:
                self._ensure_geo(known, concert, dry_run=dry_run)
                self._ensure_created_at(known, concert, dry_run=dry_run)
                self._ensure_card_url(known, concert, dry_run=dry_run)

        stats.new = len(new_events)
        logger.info(
            "Seleccionados: %s; nuevos: %s; cambios de listado: %s; sin cambios: %s; pendientes de IA: %s",
            stats.selected,
            len(new_events),
            len(changed),
            stats.skipped_unchanged,
            len(pending),
        )

        use_ai = self.settings.classification_enabled and not no_ai
        if use_ai and (new_events or pending):
            self._classifier = self.classifier_factory()
        watched = list(index.values()) if limit is None else [
            bookmark for _, bookmark in changed
        ]
        watched.extend(pending)
        for event in new_events:
            try:
                concert = self.enrichment.run(self._detail(event))
                stats.details_fetched += 1
                result = None
                pending_flag = True
                list_key = None
                if is_stale(
                    concert, moment, self.settings.past_retention_days
                ):
                    logger.info(
                        "Concierto caducado (> %s días); no se crea: %s",
                        self.settings.past_retention_days,
                        concert.source_url,
                    )
                    stats.new -= 1
                    continue
                if is_past(concert, moment):
                    pending_flag = False
                    list_key = "past"
                    logger.info(
                        "Concierto ya pasado; se omite clasificación: %s",
                        concert.source_url,
                    )
                elif use_ai:
                    result = self._classify(concert, stats)
                    pending_flag = result is None
                    if result is not None:
                        list_key = _LIST_FOR[result.classification]
                        self._apply_music_genres(concert, result)
                note = build_note(concert, result, pending=pending_flag)
                tags = tags_for_concert(concert, self.settings, result, pending=pending_flag)
                created = self._store_new(
                    dry_run=dry_run,
                    concert=concert,
                    note=note,
                    tags=tags,
                    list_key=list_key,
                )
                if created is not None:
                    self._ensure_geo(created, concert, dry_run=dry_run)
                    self._ensure_created_at(created, concert, dry_run=dry_run)
                    self._ensure_card_url(created, concert, dry_run=dry_run)
                    self._ensure_reader_content(created, concert, dry_run=dry_run)
                    self._ensure_ticket_banner(created, concert, dry_run=dry_run)
                    watched.append(created)
                if pending_flag:
                    stats.pending += 1
                elif result is not None:
                    stats.classified += 1
                    if result.classification == "IGNORE":
                        stats.ignored += 1
            except (HttpRequestError, ScrapeError, KaraKeepError) as exc:
                stats.errors += 1
                logger.error("No se pudo crear %s: %s", event.source_url, exc)
            except LLMError as exc:
                if "autenticación" in str(exc):
                    raise
                stats.errors += 1
                logger.error("No se pudo crear %s: %s", event.source_url, exc)
            except Exception as exc:
                stats.errors += 1
                logger.exception("Error inesperado creando %s: %s", event.source_url, exc)

        for event, bookmark in changed:
            try:
                concert = self.enrichment.run(self._detail(event))
                stats.details_fetched += 1
                meta = parse_meta(bookmark.note)
                preserved = extract_analysis(bookmark.note)
                stored = parse_stored_concert(bookmark.note)
                if stored and stored.genres and not concert.genres:
                    concert.genres = list(stored.genres)
                if stored is not None:
                    concert.ticket_url = prefer_ticket_url(
                        concert.ticket_url, stored.ticket_url
                    )
                pending_flag = bool(meta.get("pending")) or self._needs_classification(bookmark)
                generated = tags_for_concert(concert, self.settings, pending=pending_flag)
                tags = merge_existing_ai_tags(
                    generated,
                    bookmark,
                    set(self.settings.allow_suggested),
                )
                note = build_note(
                    concert,
                    None,
                    pending=pending_flag,
                    preserved_analysis=preserved,
                    classification_name=meta.get("classification"),
                )
                self._store_update(
                    dry_run=dry_run,
                    bookmark=bookmark,
                    title=bookmark_title(concert),
                    note=note,
                    tags=tags,
                    url=event.source_url,
                )
                self._ensure_geo(bookmark, concert, dry_run=dry_run)
                self._ensure_created_at(bookmark, concert, dry_run=dry_run)
                self._ensure_card_url(bookmark, concert, dry_run=dry_run)
                self._ensure_reader_content(bookmark, concert, dry_run=dry_run)
                self._ensure_ticket_banner(bookmark, concert, dry_run=dry_run)
                stats.updated += 1
            except (HttpRequestError, ScrapeError, KaraKeepError) as exc:
                stats.errors += 1
                logger.error("No se pudo actualizar %s: %s", event.source_url, exc)
            except Exception as exc:
                stats.errors += 1
                logger.exception("Error inesperado actualizando %s: %s", event.source_url, exc)

        if use_ai:
            for bookmark in pending:
                try:
                    concert = parse_stored_concert(bookmark.note)
                    if concert is None:
                        stats.errors += 1
                        logger.error(
                            "Bookmark %s pendiente sin datos guardados; se omite el LLM",
                            bookmark.id,
                        )
                        continue
                    result = self._classify(concert, stats)
                    if result is None:
                        stats.pending += 1
                        continue
                    self._apply_music_genres(concert, result)
                    note = build_note(concert, result, pending=False)
                    tags = tags_for_concert(concert, self.settings, result, pending=False)
                    self._store_update(
                        dry_run=dry_run,
                        bookmark=bookmark,
                        title=bookmark_title(concert),
                        note=note,
                        tags=tags,
                        url=bookmark.url,
                        list_key=_LIST_FOR[result.classification],
                        detach_pending=True,
                    )
                    self._ensure_geo(bookmark, concert, dry_run=dry_run)
                    stats.classified += 1
                    if result.classification == "IGNORE":
                        stats.ignored += 1
                except KaraKeepError as exc:
                    stats.errors += 1
                    logger.error("No se pudo reclasificar %s: %s", bookmark.id, exc)
                except LLMError as exc:
                    if "autenticación" in str(exc):
                        raise
                    stats.errors += 1
                    logger.error("No se pudo reclasificar %s: %s", bookmark.id, exc)

        stats.past += self._move_past(watched, moment, dry_run=dry_run)
        stats.deleted += self._purge_stale(
            index=index,
            watched=watched,
            now=moment,
            dry_run=dry_run,
            limit=limit,
        )
        self._log_end(stats, started)
        if (
            stats.llm_attempts
            and stats.llm_transport_failures == stats.llm_attempts
            and stats.classified == 0
        ):
            raise LLMError("El proveedor LLM falló en todas las clasificaciones")
        return 0

    def _store_new(self, *, dry_run: bool, concert: Concert, note: str, tags, list_key: str | None):
        tag_names = ", ".join(name for name, _ in tags) or "(ninguno)"
        list_name = self.settings.lists.get(list_key) if list_key else None
        geo_key = geo_list_key_for_concert(concert)
        geo_name = self.settings.geo_lists.get(geo_key, geo_key)
        card_url = bookmark_card_url(
            source_url=concert.source_url, ticket_url=concert.ticket_url
        )
        if dry_run:
            logger.info("[DRY-RUN] Crearía bookmark: %s", concert.source_url)
            logger.info("[DRY-RUN] URL de tarjeta: %s", card_url)
            created_at = concert_created_at(concert)
            if created_at is not None:
                logger.info("[DRY-RUN] createdAt del concierto: %s", created_at.isoformat())
            if list_name:
                logger.info("[DRY-RUN] Añadiría a lista: %s", list_name)
            logger.info("[DRY-RUN] Añadiría a lista geográfica: %s", geo_name)
            logger.info("[DRY-RUN] Tags: %s", tag_names)
            keys = set()
            if list_key:
                keys.add(list_key)
            keys.add(geo_key)
            return KnownBookmark(
                id=f"dry-run-{concert.source_id}",
                url=concert.source_url,
                title=bookmark_title(concert),
                note=note,
                tags=[BookmarkTag(name=name, attached_by=attached) for name, attached in tags],
                list_keys=keys,
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
        )

    def _ensure_geo(self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool) -> str:
        geo_key = geo_list_key_for_concert(concert)
        geo_name = self.settings.geo_lists.get(geo_key, geo_key)
        managed = bookmark.list_keys & GEO_LIST_KEYS
        if managed == {geo_key}:
            return "noop"
        if dry_run:
            for old in managed - {geo_key}:
                logger.info(
                    "[DRY-RUN] Quitaría de lista geográfica: %s",
                    self.settings.geo_lists.get(old, old),
                )
            if geo_key not in managed:
                logger.info("[DRY-RUN] Añadiría a lista geográfica: %s", geo_name)
            return "moved" if managed else "added"
        action = self.repo.sync_geo_list(bookmark, geo_key)
        if action != "noop":
            logger.info("Lista geográfica %s -> %s (%s)", bookmark.url, geo_name, action)
        return action

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
                "createdAt del concierto %s -> %s",
                bookmark.url,
                format_created_at_api(expected),
            )
        return action

    def _ensure_card_url(self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool) -> str:
        desired = bookmark_card_url(
            source_url=concert.source_url, ticket_url=concert.ticket_url
        )
        current = bookmark.card_url or bookmark.url
        if card_urls_match(current, desired):
            return "noop"
        if dry_run:
            logger.info(
                "[DRY-RUN] URL de tarjeta %s: %s -> %s",
                bookmark.url,
                current,
                desired,
            )
            return "updated"
        action = self.repo.set_link_url(
            bookmark,
            desired,
            refresh_banner=True,
            ticket_page_url=concert.ticket_url,
        )
        if action != "noop":
            logger.info("URL de tarjeta actualizada %s -> %s", bookmark.url, desired)
        return action

    def _ensure_reader_content(
        self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool
    ) -> str:
        """Sustituye description + reader view para evitar el CMP de cookies de Galicia."""
        if bookmark.id.startswith("dry-run-"):
            return "noop"
        description = link_description(concert)
        html = reader_html(concert)
        if dry_run:
            logger.info("[DRY-RUN] Reader limpio (Cuándo/Dónde/Precio) para %s", bookmark.url)
            return "updated"
        if not hasattr(self.repo, "set_description") or not hasattr(self.repo, "set_reader_html"):
            return "noop"
        self.repo.set_description(bookmark.id, description)
        self.repo.set_reader_html(bookmark.id, html)
        logger.info("Reader limpio aplicado: %s", bookmark.url)
        return "updated"

    def _ensure_ticket_banner(
        self, bookmark: KnownBookmark, concert: Concert, *, dry_run: bool
    ) -> str:
        """Pon como banner el cartel de la página de entradas (si hay)."""
        if bookmark.id.startswith("dry-run-"):
            return "noop"
        ticket = concert.ticket_url
        if not ticket or is_galicia_url(ticket):
            return "noop"
        if dry_run:
            logger.info("[DRY-RUN] Banner desde entradas para %s", ticket)
            return "updated"
        if not hasattr(self.repo, "set_banner_image"):
            return "noop"
        http = getattr(self.repo, "http", None)
        if http is None:
            return "noop"
        poster = fetch_ticket_poster(http, ticket)
        if poster is None:
            return "noop"
        raw, filename, content_type = poster
        self.repo.set_banner_image(
            bookmark.id,
            raw,
            filename=filename,
            content_type=content_type,
        )
        logger.info("Banner de entradas aplicado: %s (%s)", bookmark.url, filename)
        return "updated"

    def _store_update(
        self,
        *,
        dry_run: bool,
        bookmark: KnownBookmark,
        title: str,
        note: str,
        tags,
        url: str,
        list_key: str | None = None,
        detach_pending: bool = False,
    ) -> None:
        tag_names = ", ".join(name for name, _ in tags) or "(ninguno)"
        list_name = self.settings.lists.get(list_key) if list_key else None
        if dry_run:
            logger.info("[DRY-RUN] Actualizaría bookmark: %s", url)
            if list_name:
                logger.info("[DRY-RUN] Añadiría a lista: %s", list_name)
            logger.info("[DRY-RUN] Tags: %s", tag_names)
            return
        self.repo.update(bookmark, title=title, note=note, tags=tags)
        if detach_pending:
            self.repo.detach_tag(bookmark, PENDING_TAG)
        if list_key:
            self.repo.assign_list(bookmark, list_key)

    def _detail(self, event: DiscoveredEvent) -> Concert:
        concert = self.source.fetch_detail(event)
        concert.listing_fingerprint = listing_fingerprint(event)
        return concert

    def _classify(self, concert: Concert, stats: RunStats):
        stats.llm_attempts += 1
        try:
            classifier = self._classifier or self.classifier_factory()
            self._classifier = classifier
            return classifier.classify(concert, self.taste)
        except ClassificationInvalid:
            stats.errors += 1
            logger.error("Clasificación inválida para %s", concert.source_url)
            return None
        except LLMError as exc:
            stats.llm_transport_failures += 1
            if "autenticación" in str(exc):
                raise
            logger.error("Fallo del proveedor LLM en %s: %s", concert.source_url, exc)
            return None

    @staticmethod
    def _apply_music_genres(concert: Concert, result) -> None:
        genres = normalize_music_genres(result.music_genres)
        concert.genres = genres
        if genres:
            concert.field_origins["genres"] = "enriched"

    def _move_past(self, bookmarks: list[KnownBookmark], now: datetime, *, dry_run: bool) -> int:
        moved = 0
        seen: set[str] = set()
        for bookmark in bookmarks:
            if bookmark.id in seen:
                continue
            seen.add(bookmark.id)
            if not bookmark.list_keys & _ACTIVE:
                continue
            concert = parse_stored_concert(bookmark.note)
            if concert is None or not is_past(concert, now):
                continue
            if dry_run:
                logger.info("[DRY-RUN] Movería a pasados: %s", bookmark.url)
            else:
                self.repo.move_to_past(bookmark)
                logger.info("Concierto pasado: %s", bookmark.url)
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
                logger.error("No se pudo cargar la lista Pasados para purga: %s", exc)
        deleted = 0
        retention = self.settings.past_retention_days
        for bookmark in list(candidates.values()):
            concert = parse_stored_concert(bookmark.note)
            if concert is None or not is_stale(concert, now, retention):
                continue
            if dry_run:
                logger.info("[DRY-RUN] Borraría bookmark: %s", bookmark.url)
            else:
                try:
                    self.repo.delete_bookmark(bookmark)
                    logger.info("Bookmark borrado (caducado): %s", bookmark.url)
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
    def _needs_classification(bookmark: KnownBookmark) -> bool:
        names = {tag.name for tag in bookmark.tags}
        if PENDING_TAG not in names:
            return False
        return not (bookmark.list_keys & (_ACTIVE | {"past"}))

    @staticmethod
    def _log_end(stats: RunStats, started: datetime) -> None:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info(
            "Fin: encontrados=%s seleccionados=%s nuevos=%s actualizados=%s clasificados=%s "
            "ignorados=%s sin_cambios=%s fichas=%s pasados=%s borrados=%s pendientes=%s "
            "errores=%s duración=%.2fs",
            stats.discovered,
            stats.selected,
            stats.new,
            stats.updated,
            stats.classified,
            stats.ignored,
            stats.skipped_unchanged,
            stats.details_fetched,
            stats.past,
            stats.deleted,
            stats.pending,
            stats.errors,
            elapsed,
        )
