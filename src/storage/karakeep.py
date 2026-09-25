from __future__ import annotations

import logging
import time
from datetime import timezone
from pathlib import Path

from src.errors import KaraKeepError
from src.http.client import HttpClient, HttpRequestError
from src.normalize.concert_datetime import (
    created_at_matches,
    format_created_at_api,
    parse_api_datetime,
)
from src.normalize.geo import GEO_LIST_KEYS
from src.normalize.tickets import card_urls_match
from src.storage.bookmark_note import parse_stored_concert
from src.storage.models import BookmarkTag, KnownBookmark
from src.sync.identity import event_key

logger = logging.getLogger(__name__)

_TERMINAL_CRAWL = frozenset({"success", "failure"})


class KaraKeepClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        list_names: dict[str, str],
        http: HttpClient,
        default_banner_path: Path | None = None,
        crawl_poll_seconds: float = 1.5,
        crawl_timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.list_names = dict(list_names)
        self.http = http
        self.default_banner_path = default_banner_path
        self.crawl_poll_seconds = crawl_poll_seconds
        self.crawl_timeout_seconds = crawl_timeout_seconds
        self._list_ids: dict[str, str] = {}
        self._sleep = time.sleep

    def index(self, *, create_missing: bool = True) -> dict[str, KnownBookmark]:
        self._resolve_lists(create_missing=create_missing)
        found: dict[str, KnownBookmark] = {}
        for key, list_id in self._list_ids.items():
            for bookmark in self._paginate(f"/lists/{list_id}/bookmarks"):
                known = self._parse_bookmark(bookmark, {key})
                if known is None:
                    continue
                current = found.get(known.url)
                if current is None:
                    found[known.url] = known
                else:
                    current.list_keys.add(key)
                    if not current.note and known.note:
                        current.note = known.note
        return found

    def lookup_url(self, url: str) -> KnownBookmark | None:
        response = self._send("GET", "/bookmarks/check-url", params={"url": url})
        bookmark_id = (response.json() or {}).get("bookmarkId")
        if not bookmark_id:
            return None
        bookmark = self._send("GET", f"/bookmarks/{bookmark_id}").json()
        lists = self._send("GET", f"/bookmarks/{bookmark_id}/lists").json().get("lists") or []
        keys = self._keys_for_lists(lists)
        return self._parse_bookmark(bookmark, keys)

    def create(
        self,
        *,
        url: str,
        title: str,
        note: str,
        tags: list[tuple[str, str]],
        list_key: str | None,
        created_at=None,
    ) -> KnownBookmark:
        body: dict = {
            "type": "link",
            "url": url,
            "title": title[:1000],
            "note": note,
            "crawlPriority": "low",
            "source": "api",
        }
        if created_at is not None:
            body["createdAt"] = format_created_at_api(created_at)
        response = self._send(
            "POST",
            "/bookmarks",
            json=body,
        )
        payload = response.json()
        created = response.status_code == 201
        bookmark_id = payload["id"]
        if tags:
            self._attach_tags(bookmark_id, tags)
        keys: set[str] = set()
        if list_key:
            self._add_to_list(bookmark_id, list_key)
            keys.add(list_key)
        known = self._parse_bookmark(payload, keys)
        if known is None:
            known = KnownBookmark(
                id=bookmark_id,
                url=event_key(url),
                title=title,
                note=note,
                tags=[BookmarkTag(name=name, attached_by=by) for name, by in tags],
                list_keys=keys,
                created_at=parse_api_datetime(payload.get("createdAt")) or created_at,
                card_url=url,
            )
        else:
            known.note = note
            known.tags = [BookmarkTag(name=name, attached_by=by) for name, by in tags]
            known.list_keys = keys
            if created_at is not None and known.created_at is None:
                known.created_at = created_at
        # Identidad = source_url del concierto en la nota, no la URL de la tarjeta.
        known.url = self._identity_url(note, fallback=url)
        known.card_url = ((payload.get("content") or {}).get("url")) or url
        if not created:
            logger.info("KaraKeep ya tenía la URL; se reutiliza el bookmark %s", bookmark_id)
            if created_at is not None:
                self.set_created_at(known, created_at)
        else:
            self.ensure_banner_after_crawl(bookmark_id, ticket_page_url=url)
        return known

    def set_created_at(self, bookmark: KnownBookmark, created_at) -> str:
        """PATCH únicamente createdAt. Devuelve noop|updated."""
        if created_at_matches(bookmark.created_at, created_at):
            return "noop"
        iso = format_created_at_api(created_at)
        self._send(
            "PATCH",
            f"/bookmarks/{bookmark.id}",
            json={"createdAt": iso},
        )
        bookmark.created_at = created_at.astimezone(timezone.utc).replace(microsecond=0)
        return "updated"

    def set_link_url(
        self,
        bookmark: KnownBookmark,
        link_url: str,
        *,
        refresh_banner: bool = False,
        ticket_page_url: str | None = None,
    ) -> str:
        """PATCH únicamente la URL de la tarjeta. Devuelve noop|updated."""
        current = bookmark.card_url or bookmark.url
        if card_urls_match(current, link_url):
            return "noop"
        self._send(
            "PATCH",
            f"/bookmarks/{bookmark.id}",
            json={"url": link_url},
        )
        bookmark.card_url = link_url
        if refresh_banner:
            self.ensure_banner_after_crawl(
                bookmark.id,
                ticket_page_url=ticket_page_url or link_url,
            )
        return "updated"

    def set_description(self, bookmark_id: str, description: str) -> None:
        """PATCH description del link (tarjeta), sin tocar la nota."""
        self._send(
            "PATCH",
            f"/bookmarks/{bookmark_id}",
            json={"description": description},
        )

    def get_readable_content(self, bookmark_id: str) -> str:
        """Markdown del reader view (incluye CMP de Galicia si no se ha limpiado)."""
        payload = self._send("GET", f"/bookmarks/{bookmark_id}/content").json() or {}
        return str(payload.get("content") or "")

    def set_reader_html(self, bookmark_id: str, html: str) -> None:
        """Sustituye el reader con HTML propio (sin cookies) vía precrawledArchive + recrawl."""
        asset_id = self._upload_bytes("concert.html", html.encode("utf-8"), "text/html")
        payload = self._get_bookmark(bookmark_id)
        old_id = self._existing_precrawled_id(payload)
        if old_id:
            self._replace_asset(bookmark_id, old_id, asset_id)
        else:
            self._attach_asset(bookmark_id, asset_id, asset_type="precrawledArchive")
        self._recrawl_bookmark(bookmark_id)
        self._wait_for_crawl_settled(bookmark_id)

    def update(
        self,
        bookmark: KnownBookmark,
        *,
        title: str,
        note: str,
        tags: list[tuple[str, str]],
    ) -> KnownBookmark:
        self._send(
            "PATCH",
            f"/bookmarks/{bookmark.id}",
            json={"title": title[:1000], "note": note},
        )
        desired = {name: attached for name, attached in tags}
        for tag in list(bookmark.tags):
            if tag.attached_by == "ai" and tag.name not in desired:
                self._detach_tags(bookmark.id, [tag.name])
        present = {tag.name for tag in bookmark.tags}
        missing = [(name, attached) for name, attached in tags if name not in present]
        if missing:
            self._attach_tags(bookmark.id, missing)
        human = [tag for tag in bookmark.tags if tag.attached_by == "human"]
        human_names = {tag.name for tag in human}
        ai_tags = [
            BookmarkTag(name=name, attached_by=attached)
            for name, attached in tags
            if name not in human_names
        ]
        bookmark.title = title
        bookmark.note = note
        bookmark.tags = human + ai_tags
        return bookmark

    def move_to_past(self, bookmark: KnownBookmark) -> None:
        for key in ("interested", "maybe", "ignored"):
            if key in bookmark.list_keys:
                self._remove_from_list(bookmark.id, key)
                bookmark.list_keys.discard(key)
        if "past" not in bookmark.list_keys:
            self._add_to_list(bookmark.id, "past")
            bookmark.list_keys.add("past")

    def delete_bookmark(self, bookmark: KnownBookmark) -> None:
        self._send("DELETE", f"/bookmarks/{bookmark.id}")

    def list_bookmarks(self, list_key: str) -> list[KnownBookmark]:
        """Bookmarks de una lista gestionada (paginado)."""
        self._resolve_lists(create_missing=False)
        list_id = self._list_ids.get(list_key)
        if not list_id:
            raise KaraKeepError(f"Lista desconocida: {list_key}")
        found: list[KnownBookmark] = []
        for bookmark in self._paginate(f"/lists/{list_id}/bookmarks"):
            known = self._parse_bookmark(bookmark, {list_key})
            if known is not None:
                found.append(known)
        return found

    def assign_list(self, bookmark: KnownBookmark, list_key: str) -> None:
        if list_key not in bookmark.list_keys:
            self._add_to_list(bookmark.id, list_key)
            bookmark.list_keys.add(list_key)

    def remove_from_list(self, bookmark: KnownBookmark, list_key: str) -> None:
        if list_key in bookmark.list_keys:
            self._remove_from_list(bookmark.id, list_key)
            bookmark.list_keys.discard(list_key)

    def sync_geo_list(self, bookmark: KnownBookmark, geo_key: str) -> str:
        """Garantiza exactamente una lista geográfica. Devuelve noop|added|moved."""
        if geo_key not in GEO_LIST_KEYS:
            raise KaraKeepError(f"Clave geográfica desconocida: {geo_key}")
        managed = bookmark.list_keys & GEO_LIST_KEYS
        if managed == {geo_key}:
            return "noop"
        for old_key in sorted(managed - {geo_key}):
            self.remove_from_list(bookmark, old_key)
        if geo_key not in bookmark.list_keys:
            self.assign_list(bookmark, geo_key)
            return "moved" if managed else "added"
        return "moved" if managed else "noop"

    def detach_tag(self, bookmark: KnownBookmark, tag_name: str) -> None:
        self._detach_tags(bookmark.id, [tag_name])
        bookmark.tags = [tag for tag in bookmark.tags if tag.name != tag_name]

    def set_banner_image(
        self,
        bookmark_id: str,
        content: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> str:
        """Sube y deja un único bannerImage. Devuelve el assetId."""
        asset_id = self._upload_bytes(filename, content, content_type)
        snapshot = self._get_bookmark(bookmark_id)
        old_banner_id = self._existing_banner_id(snapshot)
        if old_banner_id:
            self._replace_asset(bookmark_id, old_banner_id, asset_id)
        else:
            self._attach_asset(bookmark_id, asset_id, asset_type="bannerImage")
        self._verify_single_banner(bookmark_id, asset_id)
        return asset_id

    def ensure_banner_after_crawl(
        self,
        bookmark_id: str,
        *,
        ticket_page_url: str | None = None,
    ) -> None:
        """Tras el crawl: cartel de entradas si existe; si no, banner por defecto."""
        from src.normalize.ticket_image import fetch_ticket_poster, is_galicia_url

        try:
            crawl_status = self._wait_for_crawl_settled(bookmark_id)
            if crawl_status is None:
                return
            if crawl_status == "failure":
                logger.info(
                    "Crawler falló para %s; se intenta banner igualmente",
                    bookmark_id,
                )
            poster = None
            if ticket_page_url and not is_galicia_url(ticket_page_url):
                poster = fetch_ticket_poster(self.http, ticket_page_url)
            if poster is not None:
                raw, filename, content_type = poster
                asset_id = self.set_banner_image(
                    bookmark_id,
                    raw,
                    filename=filename,
                    content_type=content_type,
                )
                logger.info(
                    "Banner desde entradas en %s (assetId=%s file=%s)",
                    bookmark_id,
                    asset_id,
                    filename,
                )
                return
            self._set_default_banner(bookmark_id)
        except Exception as exc:
            logger.error(
                "Fallo al asegurar banner del bookmark %s: %s",
                bookmark_id,
                exc,
            )

    def _set_default_banner(self, bookmark_id: str) -> None:
        path = self.default_banner_path
        if path is None or not path.is_file():
            logger.error(
                "Banner por defecto no disponible; se omite para bookmark %s (ruta=%s)",
                bookmark_id,
                path,
            )
            return
        content = path.read_bytes()
        asset_id = self.set_banner_image(
            bookmark_id,
            content,
            filename=path.name,
            content_type="image/png",
        )
        logger.info(
            "Banner por defecto adjuntado al bookmark %s (assetId=%s)",
            bookmark_id,
            asset_id,
        )

    def _set_default_banner_after_crawl(self, bookmark_id: str) -> None:
        """Compat: banner por defecto tras esperar crawl."""
        self.ensure_banner_after_crawl(bookmark_id, ticket_page_url=None)

    def _wait_for_crawl_settled(self, bookmark_id: str) -> str | None:
        deadline = time.monotonic() + self.crawl_timeout_seconds
        while True:
            payload = self._get_bookmark(bookmark_id)
            status = self._crawl_status(payload)
            if status in _TERMINAL_CRAWL:
                return status
            if time.monotonic() >= deadline:
                logger.warning(
                    "Timeout esperando crawlStatus de %s (sigue pending); "
                    "no se sube el banner para evitar carrera con el crawler",
                    bookmark_id,
                )
                return None
            self._sleep(self.crawl_poll_seconds)

    def _get_bookmark(self, bookmark_id: str) -> dict:
        return self._send("GET", f"/bookmarks/{bookmark_id}").json() or {}

    @staticmethod
    def _crawl_status(payload: dict) -> str | None:
        content = payload.get("content") or {}
        raw = content.get("crawlStatus")
        if raw is None:
            return None
        return str(raw).strip().lower() or None

    @staticmethod
    def _existing_banner_id(payload: dict) -> str | None:
        content = payload.get("content") or {}
        image_asset_id = content.get("imageAssetId")
        assets = payload.get("assets") or []
        banners = [
            asset
            for asset in assets
            if isinstance(asset, dict)
            and asset.get("assetType") == "bannerImage"
            and asset.get("id")
        ]
        if image_asset_id:
            for asset in banners:
                if asset.get("id") == image_asset_id:
                    return str(image_asset_id)
        if banners:
            return str(banners[0]["id"])
        if image_asset_id:
            return str(image_asset_id)
        return None

    @staticmethod
    def _existing_precrawled_id(payload: dict) -> str | None:
        assets = payload.get("assets") or []
        for asset in reversed(assets):
            if (
                isinstance(asset, dict)
                and asset.get("assetType") == "precrawledArchive"
                and asset.get("id")
            ):
                return str(asset["id"])
        return None

    def _verify_single_banner(self, bookmark_id: str, expected_asset_id: str) -> None:
        payload = self._get_bookmark(bookmark_id)
        banners = [
            asset
            for asset in (payload.get("assets") or [])
            if isinstance(asset, dict) and asset.get("assetType") == "bannerImage"
        ]
        if len(banners) != 1 or banners[0].get("id") != expected_asset_id:
            raise KaraKeepError(
                f"Verificación de banner fallida en {bookmark_id}: "
                f"esperado un bannerImage={expected_asset_id}, obtenido={banners}"
            )

    def _upload_asset(self, path: Path) -> str:
        content = path.read_bytes()
        return self._upload_bytes(path.name, content, "image/png")

    def _upload_bytes(self, filename: str, content: bytes, content_type: str) -> str:
        response = self._send(
            "POST",
            "/assets",
            files={"file": (filename, content, content_type)},
        )
        payload = response.json() or {}
        asset_id = payload.get("assetId")
        if not asset_id:
            raise KaraKeepError("KaraKeep no devolvió assetId al subir el asset")
        return str(asset_id)

    def _recrawl_bookmark(self, bookmark_id: str) -> None:
        # Endpoint documentado en tRPC; no hay equivalente REST en 0.33.
        url = f"{self.base_url}/api/trpc/bookmarks.recrawlBookmark"
        try:
            response = self.http.request_json(
                "POST",
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"json": {"bookmarkId": bookmark_id}},
            )
        except HttpRequestError as exc:
            raise KaraKeepError(f"Fallo de red al recrawl de {bookmark_id}") from exc
        if response.status_code == 401:
            raise KaraKeepError("KaraKeep rechazó la autenticación")
        if response.status_code >= 400:
            raise KaraKeepError(
                f"KaraKeep recrawl {bookmark_id} -> {response.status_code}"
            )

    def _attach_asset(self, bookmark_id: str, asset_id: str, *, asset_type: str) -> None:
        self._send(
            "POST",
            f"/bookmarks/{bookmark_id}/assets",
            json={"id": asset_id, "assetType": asset_type},
        )

    def _replace_asset(self, bookmark_id: str, old_asset_id: str, new_asset_id: str) -> None:
        self._send(
            "PUT",
            f"/bookmarks/{bookmark_id}/assets/{old_asset_id}",
            json={"assetId": new_asset_id},
        )

    def _ensure_lists(self) -> None:
        self._resolve_lists(create_missing=True)

    def _resolve_lists(self, *, create_missing: bool) -> None:
        response = self._send("GET", "/lists")
        existing = {
            item.get("name"): item.get("id")
            for item in (response.json().get("lists") or [])
            if item.get("name") and item.get("id")
        }
        for key, name in self.list_names.items():
            list_id = existing.get(name)
            if not list_id:
                if not create_missing:
                    logger.info("Lista ausente; no se crea en esta ejecución: %s", name)
                    continue
                created = self._send(
                    "POST",
                    "/lists",
                    json={"name": name, "icon": _icon_for(name), "type": "manual"},
                ).json()
                list_id = created["id"]
                logger.info("Lista creada en KaraKeep: %s", name)
            self._list_ids[key] = list_id

    def _paginate(self, path: str) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(100):
            params: dict[str, str | int] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            payload = self._send("GET", path, params=params).json()
            items.extend(payload.get("bookmarks") or [])
            cursor = payload.get("nextCursor")
            if not cursor:
                break
        return items

    def _parse_bookmark(self, payload: dict, list_keys: set[str]) -> KnownBookmark | None:
        content = payload.get("content") or {}
        raw_url = content.get("url")
        if not raw_url:
            return None
        tags = [
            BookmarkTag(
                name=tag.get("name") or "",
                attached_by=tag.get("attachedBy") or "human",
                id=tag.get("id"),
            )
            for tag in payload.get("tags") or []
            if tag.get("name")
        ]
        note = payload.get("note")
        return KnownBookmark(
            id=str(payload["id"]),
            url=self._identity_url(note, fallback=raw_url),
            title=payload.get("title"),
            note=note,
            tags=tags,
            list_keys=set(list_keys),
            created_at=parse_api_datetime(payload.get("createdAt")),
            card_url=raw_url,
        )

    @staticmethod
    def _identity_url(note: str | None, *, fallback: str) -> str:
        concert = parse_stored_concert(note)
        if concert and concert.source_url:
            return event_key(concert.source_url)
        if "galiciaenconcierto.com" in fallback.lower():
            return event_key(fallback)
        return fallback

    def _keys_for_lists(self, lists: list[dict]) -> set[str]:
        by_name = {name: key for key, name in self.list_names.items()}
        return {by_name[item["name"]] for item in lists if item.get("name") in by_name}

    def _attach_tags(self, bookmark_id: str, tags: list[tuple[str, str]]) -> None:
        self._send(
            "POST",
            f"/bookmarks/{bookmark_id}/tags",
            json={
                "tags": [
                    {"tagName": name, "attachedBy": attached_by} for name, attached_by in tags
                ]
            },
        )

    def _detach_tags(self, bookmark_id: str, names: list[str]) -> None:
        self._send(
            "DELETE",
            f"/bookmarks/{bookmark_id}/tags",
            json={"tags": [{"tagName": name} for name in names]},
        )

    def _add_to_list(self, bookmark_id: str, list_key: str) -> None:
        if not self._list_ids:
            self._ensure_lists()
        self._send("PUT", f"/lists/{self._list_ids[list_key]}/bookmarks/{bookmark_id}")

    def _remove_from_list(self, bookmark_id: str, list_key: str) -> None:
        if not self._list_ids:
            self._ensure_lists()
        response = self.http.request_json(
            "DELETE",
            f"{self.base_url}/api/v1/lists/{self._list_ids[list_key]}/bookmarks/{bookmark_id}",
            headers=self._headers(),
        )
        if response.status_code in {204, 400, 404}:
            return
        if response.status_code >= 400:
            raise KaraKeepError(
                f"KaraKeep DELETE lista {list_key} -> {response.status_code}"
            )

    def _send(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}/api/v1{path}"
        try:
            response = self.http.request_json(method, url, headers=self._headers(), **kwargs)
        except HttpRequestError as exc:
            raise KaraKeepError(f"Fallo de red con KaraKeep en {path}") from exc
        if response.status_code == 401:
            raise KaraKeepError("KaraKeep rechazó la autenticación")
        if response.status_code >= 400:
            raise KaraKeepError(f"KaraKeep {method} {path} -> {response.status_code}")
        return response

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}


def _icon_for(name: str) -> str:
    first = name.split(" ", 1)[0]
    if first and not first[0].isascii():
        return first
    return "📁"
