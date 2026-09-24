from __future__ import annotations

import logging
import mimetypes
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from src.http.client import HttpClient, HttpRequestError
from src.normalize.tickets import normalize_ticket_url

logger = logging.getLogger(__name__)

# Varios ticketing (p. ej. Entradium) sirven un interstitial sin UA de navegador.
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_META_KEYS = (
    "og:image",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
)

_IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp|gif)(?:$|\?)", re.I)


def is_galicia_url(url: str | None) -> bool:
    if not url:
        return False
    return "galiciaenconcierto.com" in url.lower()


def extract_ticket_image_url(html: str, *, page_url: str) -> str | None:
    """Elige la mejor URL de cartel en una página de entradas."""
    soup = BeautifulSoup(html, "lxml")
    for key in _META_KEYS:
        for tag in soup.select(f'meta[property="{key}"], meta[name="{key}"]'):
            raw = (tag.get("content") or "").strip()
            if not raw:
                continue
            absolute = urljoin(page_url, raw)
            if absolute.lower().startswith("http") and not is_galicia_url(absolute):
                return absolute
    link = soup.select_one('link[rel="image_src"]')
    if link and link.get("href"):
        absolute = urljoin(page_url, link["href"].strip())
        if absolute.lower().startswith("http") and not is_galicia_url(absolute):
            return absolute
    return None


def _filename_for(url: str, content_type: str | None) -> str:
    path = urlsplit(url).path.rsplit("/", 1)[-1] or "poster"
    path = path.split("?", 1)[0]
    if "." not in path:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        path = f"poster{ext}"
    return path[:180]


def fetch_ticket_poster(
    http: HttpClient,
    ticket_url: str | None,
) -> tuple[bytes, str, str] | None:
    """Descarga el cartel de la página de entradas.

    Devuelve (bytes, filename, content_type) o None.
    """
    page = normalize_ticket_url(ticket_url)
    if not page or is_galicia_url(page):
        return None
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"}
    try:
        html = http.get_text(page, headers=headers)
    except HttpRequestError as exc:
        logger.info("No se pudo abrir página de entradas %s: %s", page, exc)
        return None
    image_url = extract_ticket_image_url(html, page_url=page)
    if not image_url:
        logger.info("Sin og:image en entradas: %s", page)
        return None
    try:
        response = http.request_json(
            "GET",
            image_url,
            headers={"User-Agent": BROWSER_UA, "Accept": "image/*,*/*;q=0.8"},
        )
    except HttpRequestError as exc:
        logger.info("No se pudo descargar cartel %s: %s", image_url, exc)
        return None
    if response.status_code >= 400 or not response.content:
        logger.info("Cartel HTTP %s en %s", response.status_code, image_url)
        return None
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if content_type and not content_type.startswith("image/"):
        # Algunos CDN no mandan content-type útil; aceptar por extensión.
        if not _IMAGE_EXT.search(image_url):
            logger.info("Respuesta no-imagen (%s) en %s", content_type, image_url)
            return None
        content_type = "image/jpeg"
    if not content_type:
        content_type = "image/jpeg"
    if len(response.content) < 2000:
        logger.info("Cartel demasiado pequeño (%s B) en %s", len(response.content), image_url)
        return None
    filename = _filename_for(image_url, content_type)
    return response.content, filename, content_type
