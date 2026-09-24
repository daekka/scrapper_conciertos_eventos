from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.errors import ScrapeError
from src.http.client import HttpClient, HttpRequestError
from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.listing_fingerprint import listing_fingerprint
from src.sources.base import ConcertSource
from src.sources.galicia_en_concierto.agenda_parser import parse_month_html
from src.sources.galicia_en_concierto.detail_parser import concert_from_detail
from src.sync.past import is_discovered_past

logger = logging.getLogger(__name__)


class GaliciaEnConciertoSource(ConcertSource):
    def __init__(
        self,
        *,
        http: HttpClient,
        base_url: str,
        agenda_path: str,
        months_ahead: int,
        timezone_name: str,
        source_name: str = "galicia_en_concierto",
    ) -> None:
        self.name = source_name
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.agenda_path = agenda_path if agenda_path.startswith("/") else f"/{agenda_path}"
        self.months_ahead = months_ahead
        self.timezone_name = timezone_name

    def discover(self, *, now: datetime) -> list[DiscoveredEvent]:
        tz = ZoneInfo(self.timezone_name)
        current = now.astimezone(tz)
        year, month = current.year, current.month
        found: dict[str, DiscoveredEvent] = {}
        failures = 0
        for _ in range(self.months_ahead):
            url = self._month_url(year, month)
            try:
                html = self.http.get_text(url)
            except HttpRequestError:
                failures += 1
                logger.error("No se pudo leer la vista mensual %s", url)
            else:
                events = parse_month_html(
                    html,
                    view_year=year,
                    view_month=month,
                    source=self.name,
                    scraped_at=now,
                )
                logger.info("Vista %s-%02d: %s eventos", year, month, len(events))
                for event in events:
                    found.setdefault(event.source_id, event)
            month += 1
            if month == 13:
                month = 1
                year += 1
        if failures == self.months_ahead:
            raise ScrapeError("Fallaron todas las vistas mensuales de Galicia en Concierto")
        kept: list[DiscoveredEvent] = []
        omitted = 0
        for event in found.values():
            if is_discovered_past(event, now, self.timezone_name):
                omitted += 1
                continue
            kept.append(event)
        logger.info(
            "Descubiertos %s eventos únicos (%s pasados omitidos del listado)",
            len(kept),
            omitted,
        )
        return kept

    def fetch_detail(self, event: DiscoveredEvent) -> Concert:
        html = self.http.get_text(event.detail_url)
        concert = concert_from_detail(html, event, timezone_name=self.timezone_name)
        concert.listing_fingerprint = listing_fingerprint(event)
        return concert

    def _month_url(self, year: int, month: int) -> str:
        path = self.agenda_path.rstrip("/")
        return (
            f"{self.base_url}{path}/action~month/exact_date~1-{month}-{year}/"
        )
