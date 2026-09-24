from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from src.models.discovered import DiscoveredEvent
from src.normalize.dates import parse_listing_when
from src.normalize.places import split_location
from src.normalize.tickets import normalize_ticket_url
from src.normalize.urls import canonicalize_url

def _id_from_classes(classes: list[str], instance: bool) -> str | None:
    prefix = "ai1ec-event-instance-id-" if instance else "ai1ec-event-id-"
    for name in classes:
        if name.startswith(prefix) and name[len(prefix) :].isdigit():
            return name[len(prefix) :]
    return None


def _ticket_url(container: Tag | None) -> str | None:
    if container is None:
        return None
    node = container.select_one("[data-ticket-url]")
    if node is None:
        return None
    raw = (node.get("data-ticket-url") or "").strip()
    return normalize_ticket_url(raw)


def parse_month_html(
    html: str,
    *,
    view_year: int,
    view_month: int,
    source: str,
    scraped_at: datetime | None = None,
) -> list[DiscoveredEvent]:
    soup = BeautifulSoup(html, "lxml")
    moment = scraped_at or datetime.now(timezone.utc)
    containers: dict[str, Tag] = {}
    for anchor in soup.select("a.ai1ec-event-container"):
        instance_id = _id_from_classes(anchor.get("class") or [], instance=True)
        if instance_id:
            containers[instance_id] = anchor

    events: list[DiscoveredEvent] = []
    seen: set[str] = set()
    for popup in soup.select("div.ai1ec-popup"):
        classes = popup.get("class") or []
        event_id = _id_from_classes(classes, instance=False)
        instance_id = _id_from_classes(classes, instance=True)
        link = popup.select_one("a.ai1ec-load-event")
        title_node = popup.select_one(".ai1ec-popup-title a")
        if link is None or title_node is None:
            continue
        href = link.get("href") or ""
        if not href or href.endswith("#"):
            continue
        title = " ".join(title_node.get_text(" ", strip=True).split())
        if not title:
            continue
        location_node = popup.select_one(".ai1ec-event-location")
        venue, city = split_location(location_node.get_text(" ", strip=True) if location_node else None)
        time_node = popup.select_one(".ai1ec-event-time")
        time_text = time_node.get_text(" ", strip=True) if time_node else ""
        container = containers.get(instance_id or "")
        container_classes = container.get("class") if container else []
        all_day_hint = "ai1ec-allday" in (container_classes or [])
        when = parse_listing_when(
            time_text,
            view_year=view_year,
            view_month=view_month,
            all_day_hint=all_day_hint,
        )
        swatch = popup.select_one(".ai1ec-color-swatch")
        category = (swatch.get("title") or "").strip() if swatch else None
        source_id = f"{event_id or 'unknown'}:{instance_id or 'unknown'}"
        if source_id in seen:
            continue
        seen.add(source_id)
        events.append(
            DiscoveredEvent(
                source=source,
                event_id=event_id,
                instance_id=instance_id,
                source_id=source_id,
                source_url=canonicalize_url(href, force_trailing_slash=True),
                detail_url=canonicalize_url(
                    href, force_trailing_slash=True, drop_instance=False
                ),
                title=title,
                venue=venue,
                city=city,
                date=when.date,
                end_date=when.end_date,
                start_time=when.start_time,
                end_time=when.end_time,
                all_day=when.all_day,
                ticket_url=_ticket_url(container),
                category_label=category or None,
                scraped_at=moment,
            )
        )
    return events
