from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BookmarkTag:
    name: str
    attached_by: str
    id: str | None = None


@dataclass
class KnownBookmark:
    id: str
    url: str  # Identidad del concierto (source_url canónica)
    title: str | None
    note: str | None
    tags: list[BookmarkTag] = field(default_factory=list)
    list_keys: set[str] = field(default_factory=set)
    created_at: datetime | None = None
    card_url: str | None = None  # URL real en KaraKeep (tarjeta)
