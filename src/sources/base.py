from __future__ import annotations

from datetime import datetime

from src.models.discovered import Concert, DiscoveredEvent


class ConcertSource:
    name: str

    def discover(self, *, now: datetime) -> list[DiscoveredEvent]:
        raise NotImplementedError

    def fetch_detail(self, event: DiscoveredEvent) -> Concert:
        raise NotImplementedError
