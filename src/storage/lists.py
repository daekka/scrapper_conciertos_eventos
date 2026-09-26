from __future__ import annotations

from src.config import Settings
from src.models.classification import ClassificationResult
from src.models.discovered import Concert
from src.normalize.genres import normalize_music_genres
from src.normalize.tags import CITY_TAGS, PROVINCE_TAGS, dedupe_tags, slug_tag
from src.sources.coruna_gal.tipos import tipo_keys_from_labels
from src.storage.models import KnownBookmark

PENDING_TAG = "pending-classification"


def tags_for_concert(
    concert: Concert,
    settings: Settings,
    result: ClassificationResult | None = None,
    *,
    pending: bool = False,
) -> list[tuple[str, str]]:
    names = list(settings.base_tags)
    city = CITY_TAGS.get((concert.city or "").casefold())
    if city:
        names.append(city)
    province = PROVINCE_TAGS.get((concert.province or "").casefold())
    if province:
        names.append(province)
    if concert.free:
        names.append("gratis")
    title = f"{concert.title} {concert.event_name or ''}"
    if "festival" in title.casefold():
        names.append("festival")
    for genre in normalize_music_genres(concert.genres):
        slug = slug_tag(genre)
        if slug and 2 <= len(slug) <= 40:
            names.append(slug)
    allowed = set(settings.allow_suggested)
    if result is not None:
        for suggestion in result.suggested_tags:
            slug = slug_tag(suggestion)
            if slug in allowed:
                names.append(slug)
    if pending:
        names.append(PENDING_TAG)
    return [(name, "ai") for name in dedupe_tags(names)]


def tags_for_coruna(
    concert: Concert,
    *,
    base_tags: list[str],
    allow_suggested: list[str],
) -> list[tuple[str, str]]:
    """Tags del pipeline Coruña: base + tipologías + gratis."""
    names = list(base_tags)
    for key in tipo_keys_from_labels(concert.categories):
        names.append(key)
    if concert.free:
        names.append("gratis")
    allowed = set(allow_suggested) | set(base_tags)
    names = [n for n in names if n in allowed]
    return [(name, "ai") for name in dedupe_tags(names)]


def merge_existing_ai_tags(
    generated: list[tuple[str, str]],
    bookmark: KnownBookmark,
    allowed: set[str],
) -> list[tuple[str, str]]:
    names = [name for name, _ in generated]
    for tag in bookmark.tags:
        if tag.attached_by == "ai" and tag.name in allowed and tag.name not in names:
            if tag.name == PENDING_TAG and PENDING_TAG not in names:
                continue
            names.append(tag.name)
    return [(name, "ai") for name in dedupe_tags(names)]
