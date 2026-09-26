"""Carga del RSS de ocio/cultura de coruna.gal."""

from __future__ import annotations

import html as htmlmod
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from src.errors import ScrapeError
from src.http.client import HttpClient, HttpRequestError

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"

_IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp|gif)(?:$|\?)", re.I)


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    tags: list[str]
    image_url: str | None = None


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;|/]+", htmlmod.unescape(raw))
    seen: set[str] = set()
    tags: list[str] = []
    for part in parts:
        tag = re.sub(r"\s+", " ", part).strip(" .-_")
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def _strip_html(value: str | None) -> str:
    text = value or ""
    if "<" in text:
        text = re.sub(r"<[^>]+>", " ", text)
        text = htmlmod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_image(url: str, typ: str = "") -> bool:
    if typ.lower().startswith("image/"):
        return True
    return bool(_IMAGE_EXT.search(url))


def parse_item_image(item: ET.Element) -> str | None:
    """Prioriza media:content, luego thumbnail, luego itunes:image."""
    for content in item.findall(MEDIA + "content"):
        url = (content.get("url") or "").strip()
        typ = content.get("type") or ""
        if url and _looks_like_image(url, typ):
            return url
    for thumb in item.findall(MEDIA + "thumbnail"):
        url = (thumb.get("url") or "").strip()
        if url:
            return url
    image = item.find(ITUNES + "image")
    if image is not None:
        href = (image.get("href") or image.get("url") or "").strip()
        if href:
            return href
    return None


def parse_feed_xml(content: str) -> list[FeedItem]:
    root = ET.fromstring(content)
    items = root.findall(".//item")
    if items:
        rows: list[FeedItem] = []
        for item in items:
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            title = _strip_html(item.findtext("title") or "")
            tags = parse_tags(item.findtext(ITUNES + "keywords") or "")
            rows.append(
                FeedItem(
                    title=title,
                    url=link,
                    tags=tags,
                    image_url=parse_item_image(item),
                )
            )
        return rows

    entries = root.findall(".//" + ATOM + "entry")
    if not entries:
        return []
    rows = []
    for entry in entries:
        links = entry.findall(ATOM + "link")
        href = next(
            (x.get("href", "") for x in links if x.get("rel", "alternate") == "alternate"),
            next((x.get("href", "") for x in links), ""),
        )
        if not href:
            continue
        rows.append(
            FeedItem(
                title=_strip_html(entry.findtext(ATOM + "title") or ""),
                url=href,
                tags=[],
                image_url=parse_item_image(entry),
            )
        )
    return rows


def load_feed(http: HttpClient, feed_url: str) -> list[FeedItem]:
    match = re.search(r"rss\.app/r/feed/([\w-]+)", feed_url)
    candidates = [feed_url]
    if match:
        candidates.append(f"https://rss.app/feeds/{match.group(1)}.xml")
    failures: list[str] = []
    for candidate in candidates:
        try:
            content = http.get_text(
                candidate,
                headers={
                    "Accept": "application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.5"
                },
            )
            items = parse_feed_xml(content)
            if items:
                return items
            failures.append(f"{candidate}: XML sin noticias")
        except (HttpRequestError, ET.ParseError, UnicodeError) as exc:
            failures.append(f"{candidate}: {exc}")
    raise ScrapeError(
        "No se pudo leer el RSS de Coruña. " + " | ".join(failures)
    )
