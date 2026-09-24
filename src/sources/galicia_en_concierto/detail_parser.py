from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from src.models.discovered import Concert, DiscoveredEvent
from src.normalize.cookies import (
    CMP_SELECTORS,
    is_cookie_consent_text,
    strip_cookie_consent,
)
from src.normalize.dates import parse_iso_datetime
from src.normalize.places import province_for_category, province_for_city, split_location
from src.normalize.prices import parse_price
from src.normalize.tickets import normalize_ticket_url, prefer_ticket_url
from src.normalize.urls import canonicalize_url

_FESTIVAL = re.compile(r"\b(festival|fiesta|ciclo)\b", re.I)
_CMP_ANCESTOR = re.compile(
    r"(cookie|cli-bar|cli-modal|gdpr|consent)",
    re.I,
)


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    for tag in soup.select(f'meta[property="{prop}"]'):
        content = (tag.get("content") or "").strip()
        if content:
            return content
    return None


def _strip_cmp_nodes(soup: BeautifulSoup) -> None:
    for selector in CMP_SELECTORS:
        for node in soup.select(selector):
            node.decompose()


def _inside_cmp(node) -> bool:
    for parent in node.parents:
        if parent is None or getattr(parent, "name", None) in {None, "[document]"}:
            break
        identity = " ".join(
            filter(
                None,
                [
                    parent.get("id") if hasattr(parent, "get") else None,
                    " ".join(parent.get("class") or []) if hasattr(parent, "get") else None,
                ],
            )
        )
        if identity and _CMP_ANCESTOR.search(identity):
            return True
    return False


def _description(soup: BeautifulSoup) -> str | None:
    _strip_cmp_nodes(soup)
    for paragraph in soup.select("p"):
        if _inside_cmp(paragraph):
            continue
        text = _text(paragraph)
        if not text or is_cookie_consent_text(text):
            continue
        cleaned = strip_cookie_consent(text)
        if cleaned:
            return cleaned
    og = _meta(soup, "og:description")
    return strip_cookie_consent(og) if og else None


def concert_from_detail(
    html: str,
    discovered: DiscoveredEvent,
    *,
    timezone_name: str = "Europe/Madrid",
    scraped_at: datetime | None = None,
) -> Concert:
    soup = BeautifulSoup(html, "lxml")
    origins: dict[str, str] = {}
    tz = ZoneInfo(timezone_name)
    moment = scraped_at or datetime.now(timezone.utc)

    title = _text(soup.select_one("h1.entry-title")) or discovered.title
    origins["title"] = "source"

    start = parse_iso_datetime(_text(soup.select_one(".dt-start")))
    end = parse_iso_datetime(_text(soup.select_one(".dt-end")))
    date = start.astimezone(tz).date() if start else discovered.date
    start_time = start.astimezone(tz).time().replace(microsecond=0) if start else discovered.start_time
    end_time = end.astimezone(tz).time().replace(microsecond=0) if end else discovered.end_time
    end_date = end.astimezone(tz).date() if end else discovered.end_date
    if start:
        origins["date"] = "source"
        origins["start_time"] = "source"
    elif discovered.date:
        origins["date"] = "source"
    if end:
        origins["end_time"] = "source"

    location = _text(soup.select_one(".p-location"))
    venue, city = split_location(location) if location else (discovered.venue, discovered.city)
    if not location:
        venue, city = discovered.venue, discovered.city
    if venue:
        origins["venue"] = "source" if location else "source"
    if city and location and "," in location:
        origins["city"] = "inferred"
    elif city and location and "," not in location:
        origins["city"] = "inferred"
    elif city:
        origins["city"] = "source"

    categories = [_text(node) for node in soup.select("a.ai1ec-category")]
    categories = [item for item in categories if item]
    category_label = categories[0] if categories else discovered.category_label
    province = province_for_city(city) or province_for_category(category_label)
    if province:
        origins["province"] = "inferred"
    if province_for_city(city) or city:
        origins["country"] = "inferred"

    price_text = _text(soup.select_one(".ai1ec-cost .ai1ec-field-value"))
    price, currency, free = parse_price(price_text or None)
    if price_text:
        origins["price"] = "source"
        origins["free"] = "source"
        if currency:
            origins["currency"] = "source"

    ticket = None
    ticket_node = soup.select_one("a.ai1ec-tickets")
    if ticket_node and ticket_node.get("href"):
        ticket = normalize_ticket_url(ticket_node.get("href"))
    ticket = prefer_ticket_url(ticket, discovered.ticket_url)
    if ticket:
        origins["ticket_url"] = "source"

    image = _meta(soup, "og:image")
    if image and not image.startswith("http"):
        image = None
    if image:
        origins["image_url"] = "source"

    published = parse_iso_datetime(_meta(soup, "article:published_time"))
    modified = parse_iso_datetime(_meta(soup, "article:modified_time"))
    if published:
        origins["published_at"] = "source"
    if modified:
        origins["modified_at"] = "source"

    description = _description(soup)
    if description:
        origins["description"] = "source"

    if _FESTIVAL.search(title):
        artist = None
        event_name = title
        origins["event_name"] = "inferred"
    else:
        artist = title
        event_name = None
        origins["artist"] = "inferred"

    all_day = discovered.all_day or (start_time is None and date is not None and end_time is None)
    if discovered.all_day:
        start_time = None
        if discovered.end_date:
            end_date = discovered.end_date
        end_time = None

    return Concert(
        source=discovered.source,
        source_id=discovered.source_id,
        source_url=discovered.source_url,
        title=title,
        artist=artist,
        event_name=event_name,
        description=description,
        date=date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        all_day=discovered.all_day,
        timezone=timezone_name,
        venue=venue,
        city=city,
        province=province,
        country="España" if province or city else None,
        price=price,
        currency=currency,
        free=free,
        image_url=image,
        ticket_url=ticket,
        categories=categories,
        published_at=published,
        modified_at=modified,
        scraped_at=moment,
        field_origins=origins,
        listing_fingerprint=None,
    )
