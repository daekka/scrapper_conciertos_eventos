from __future__ import annotations

from src.normalize.listing_fingerprint import listing_fingerprint
from src.storage.bookmark_note import parse_meta
from src.models.discovered import DiscoveredEvent
from src.storage.models import KnownBookmark


def same_listing(event: DiscoveredEvent, bookmark: KnownBookmark) -> bool:
    stored = parse_meta(bookmark.note).get("listing_fp")
    if not stored:
        return False
    return stored == listing_fingerprint(event)
