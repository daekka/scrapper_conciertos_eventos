"""Fuente RSS de ocio/cultura de coruna.gal."""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from src.errors import ScrapeError
from src.http.client import HttpClient, HttpRequestError
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.listing_fingerprint import listing_fingerprint
from src.sources.base import ConcertSource
from src.sources.coruna_gal.detail_parser import concert_from_detail, source_id_from_url
from src.sources.coruna_gal.feed import load_feed
from src.sync.past import is_discovered_past

logger = logging.getLogger(__name__)


def _canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


class CorunaGalSource(ConcertSource):
    def __init__(
        self,
        *,
        http: HttpClient,
        feed_url: str,
        timezone_name: str,
        source_name: str = "coruna_gal",
    ) -> None:
        self.name = source_name
        self.http = http
        self.feed_url = feed_url
        self.timezone_name = timezone_name

    def discover(self, *, now: datetime) -> list[DiscoveredEvent]:
        try:
            items = load_feed(self.http, self.feed_url)
        except ScrapeError:
            raise
        except HttpRequestError as exc:
            raise ScrapeError(str(exc)) from exc

        found: dict[str, DiscoveredEvent] = {}
        skipped_past = 0
        for item in items:
            if not item.url:
                continue
            source_url = _canonical_url(item.url)
            source_id = source_id_from_url(source_url)
            event = DiscoveredEvent(
                source=self.name,
                event_id=source_id,
                instance_id=None,
                source_id=source_id,
                source_url=source_url,
                detail_url=source_url,
                title=item.title or source_id,
                city="A Coruña",
                keywords=list(item.tags),
                image_url=item.image_url,
                scraped_at=now,
            )
            # Sin fechas en el RSS no se puede filtrar pasados aquí.
            if event.date is not None and is_discovered_past(
                event, now, self.timezone_name
            ):
                skipped_past += 1
                continue
            found.setdefault(event.source_id, event)

        events = list(found.values())
        logger.info(
            "RSS Coruña: %s ítems, %s únicos, omitidos_pasados=%s",
            len(items),
            len(events),
            skipped_past,
        )
        return events

    def fetch_detail(self, event: DiscoveredEvent) -> Concert:
        try:
            html = self.http.get_text(event.detail_url or event.source_url)
        except HttpRequestError as exc:
            raise ScrapeError(f"No se pudo leer la ficha {event.source_url}: {exc}") from exc
        concert = concert_from_detail(event, html, final_url=event.source_url)
        concert.listing_fingerprint = listing_fingerprint(event)
        return concert
