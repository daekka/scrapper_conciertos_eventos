"""Parser de fichas de evento coruna.gal (detalleEvento / JSON-LD)."""

from __future__ import annotations

import html as htmlmod
import json
import re
from datetime import date, datetime, time
from html.parser import HTMLParser
from urllib.parse import urlparse

from src.models.discovered import Concert, DiscoveredEvent, Origin
from src.sources.coruna_gal.tipos import infer_tipos


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.blocks: list[str] = []
        self.scripts: list[str] = []
        self.stack: list[list] = []
        self.skip = 0
        self.script: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip += 1
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.script = []
        if tag in ("title", "h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "td", "th", "div"):
            self.stack.append([tag, []])
        if tag in ("br", "hr") and self.stack:
            self.stack[-1][1].append(" ")

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if not self.skip:
            for _, chunks in self.stack:
                chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip = max(0, self.skip - 1)
        if self.stack and self.stack[-1][0] == tag:
            _, chunks = self.stack.pop()
            s = re.sub(r"\s+", " ", "".join(chunks)).strip()
            if s and len(s) < 2000:
                if tag == "title":
                    self.title = s
                elif tag != "div" or not any(s == x for x in self.blocks):
                    self.blocks.append(s)


_LABELS = {
    "audience": r"(?:a qui[eé]n(?:es)? (?:va )?dirigid[oa]s?|destinatari[oa]s?|p[uú]blico objetivo|dirigido a)",
    "cuando": r"(?:cu[aá]ndo|cu[aá]ndo se celebra|celebraci[oó]n)",
    "donde": r"(?:d[oó]nde|lugar|ubicaci[oó]n|localizaci[oó]n|sede|enderezo)",
    "horario": r"(?:horario|hora(?:s)?(?: de inicio)?)",
    "fechas": r"(?:fechas?|per[ií]odo|calendario)",
    "inscripciones": r"(?:inscripci[oó]n(?:es)?|matr[ií]cula|registro|plazo de inscripci[oó]n|prezo)",
    "duracion": r"(?:duraci[oó]n)",
}


def text_of(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"</(p|li|div|h\d)>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = htmlmod.unescape(fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return re.sub(r"\s+\.", ".", fragment)


def first_match(pattern: str, html: str, flags=re.I | re.S) -> str:
    m = re.search(pattern, html, flags)
    return text_of(m.group(1)) if m else ""


def tidy_date(value: str) -> str:
    return re.sub(r"\.0$", "", value.strip()) if value else ""


def flatten_jsonld(node):
    if isinstance(node, list):
        for value in node:
            yield from flatten_jsonld(value)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from flatten_jsonld(node["@graph"])


def clean(value) -> str:
    if isinstance(value, dict):
        return clean(value.get("name") or value.get("address") or value.get("url") or "")
    if isinstance(value, list):
        return "; ".join(filter(None, map(clean, value)))
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_coruna(html: str) -> dict[str, str]:
    """Extrae campos del bloque detalleEvento de las fichas de coruna.gal."""
    m = re.search(
        r'<div[^>]*class=["\'][^"\']*\bdetalleEvento\b[^"\']*["\'][^>]*>(.*)',
        html,
        re.I | re.S,
    )
    if not m:
        return {}
    block = m.group(1)
    cut = re.search(r'class=["\'][^"\']*\blistadoEvento\b', block, re.I)
    if cut:
        block = block[: cut.start()]
    data: dict[str, str] = {}
    data["titulo"] = first_match(r'<h1[^>]*property=["\']name["\'][^>]*>(.*?)</h1>', block)
    data["audience"] = first_match(
        r'<p[^>]*class=["\'][^"\']*\bcategoria\b[^"\']*["\'][^>]*>(.*?)</p>', block
    )
    data["cuando"] = first_match(
        r'<section[^>]*class=["\'][^"\']*\bfechas\b[^"\']*["\'][^>]*>.*?'
        r'<p[^>]*class=["\'][^"\']*\bfechas\b[^"\']*["\'][^>]*>(.*?)</p>',
        block,
    )
    if not data["cuando"]:
        data["cuando"] = first_match(
            r'<p[^>]*class=["\'][^"\']*\bfechas\b[^"\']*["\'][^>]*>(.*?)</p>', block
        )
    start = tidy_date(
        first_match(r'<meta\s+property=["\']startDate["\']\s+content=["\']([^"\']+)["\']', block)
    )
    end = tidy_date(
        first_match(r'<meta\s+property=["\']endDate["\']\s+content=["\']([^"\']+)["\']', block)
    )
    if start:
        data["start_raw"] = start
    if end:
        data["end_raw"] = end
    if start and end and start != end:
        data["fechas"] = f"{start} - {end}"
    elif start:
        data["fechas"] = start
    elif data.get("cuando"):
        data["fechas"] = data["cuando"]
    data["horario"] = first_match(
        r'<div[^>]*class=["\'][^"\']*\bhorario\b[^"\']*["\'][^>]*>(.*?)</div>', block
    )
    if not data["horario"]:
        data["horario"] = first_match(
            r'<section[^>]*class=["\'][^"\']*\bhorario\b[^"\']*["\'][^>]*>(.*?)</section>',
            block,
        )
    data["duracion"] = first_match(
        r'<p[^>]*class=["\'][^"\']*\bduracion\b[^"\']*["\'][^>]*>(.*?)</p>', block
    )
    data["donde"] = first_match(
        r'<p[^>]*class=["\'][^"\']*\bdireccion\b[^"\']*["\'][^>]*>(.*?)</p>', block
    )
    insc = first_match(
        r'<section[^>]*class=["\'][^"\']*\bfechaInscripcion\b[^"\']*["\'][^>]*>.*?'
        r'<p[^>]*class=["\'][^"\']*\bfechaInscripcion\b[^"\']*["\'][^>]*>(.*?)</p>',
        block,
    )
    if not insc:
        insc = first_match(
            r'<p[^>]*class=["\'][^"\']*\bfechaInscripcion\b[^"\']*["\'][^>]*>(.*?)</p>',
            block,
        )
    precio = first_match(
        r'<div[^>]*class=["\'][^"\']*\bpreciosuceso\b[^"\']*["\'][^>]*>(.*?)</div>', block
    )
    if insc and precio:
        data["inscripciones"] = f"{insc} | {precio}"
    else:
        data["inscripciones"] = insc or precio
    if precio and re.search(r"\bgratis\b|\bgratuít|\bgratuit", precio, re.I):
        data["free"] = "1"
    return {k: v for k, v in data.items() if v}


def parse_iso_datetime(raw: str | None) -> tuple[date | None, time | None]:
    if not raw:
        return None, None
    value = tidy_date(raw)
    value = value.replace("Z", "+00:00")
    try:
        if "T" in value or " " in value:
            normalized = value.replace(" ", "T", 1)
            dt = datetime.fromisoformat(normalized)
            return dt.date(), dt.time().replace(microsecond=0)
        return date.fromisoformat(value[:10]), None
    except ValueError:
        return None, None


_TIME_IN_TEXT = re.compile(r"\b(\d{1,2})[:hH\.](\d{2})\b")


def parse_time_from_text(value: str | None) -> time | None:
    if not value:
        return None
    m = _TIME_IN_TEXT.search(value)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def source_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    return slug or re.sub(r"\W+", "-", url)[:80]


def _compose_description(fields: dict[str, str]) -> str | None:
    lines: list[str] = []
    if fields.get("audience"):
        lines.append(f"**A quién va dirigido:** {fields['audience']}")
    if fields.get("cuando"):
        lines.append(f"**Cuándo (texto):** {fields['cuando']}")
    if fields.get("horario"):
        lines.append(f"**Horario:** {fields['horario']}")
    if fields.get("duracion"):
        lines.append(f"**Duración:** {fields['duracion']}")
    if fields.get("inscripciones"):
        lines.append(f"**Inscripciones / precio:** {fields['inscripciones']}")
    return "\n\n".join(lines) if lines else None


def concert_from_detail(
    event: DiscoveredEvent,
    html: str,
    *,
    final_url: str | None = None,
) -> Concert:
    page = _Page()
    page.feed(html)
    fields = extract_coruna(html)

    # Fallback genérico por etiquetas "Campo: valor"
    for block in page.blocks:
        if len(block) > 700:
            continue
        for field, label in _LABELS.items():
            if fields.get(field):
                continue
            m = re.match(r"^\s*(?:" + label + r")\s*[:：–—-]\s*(.{2,350})$", block, re.I)
            if m:
                fields[field] = m.group(1).strip()

    # JSON-LD Event
    for script in page.scripts:
        try:
            objects = list(flatten_jsonld(json.loads(script)))
        except (ValueError, TypeError):
            continue
        for obj in objects:
            kind = obj.get("@type", "")
            if "Event" not in clean(kind):
                continue
            fields.setdefault("titulo", clean(obj.get("name")))
            fields.setdefault("donde", clean(obj.get("location")))
            if not fields.get("start_raw"):
                start = clean(obj.get("startDate"))
                if start:
                    fields["start_raw"] = start
            if not fields.get("end_raw"):
                end = clean(obj.get("endDate"))
                if end:
                    fields["end_raw"] = end
            offers = clean(obj.get("offers"))
            if offers and not fields.get("inscripciones"):
                fields["inscripciones"] = offers
            duration = clean(obj.get("duration"))
            if duration and not fields.get("duracion"):
                fields["duracion"] = duration

    title = fields.get("titulo") or event.title or page.title or "Evento Coruña"
    start_date, start_time = parse_iso_datetime(fields.get("start_raw"))
    end_date, end_time = parse_iso_datetime(fields.get("end_raw"))
    if start_time is None:
        start_time = parse_time_from_text(fields.get("horario")) or parse_time_from_text(
            fields.get("cuando")
        )
    if end_date is None and fields.get("fechas") and " - " in fields["fechas"]:
        # ya cubierto por start/end raw habitualmente
        pass
    all_day = bool(start_date and start_time is None)

    keywords = list(event.keywords) if getattr(event, "keywords", None) else []
    tipos = infer_tipos(" ".join(keywords), title, fields.get("audience", ""))
    venue = fields.get("donde")
    city = "A Coruña"
    description = _compose_description(fields)
    free = fields.get("free") == "1" or (
        bool(fields.get("inscripciones"))
        and bool(re.search(r"\bgratis\b|\bgratuít|\bgratuit", fields.get("inscripciones", ""), re.I))
    )

    source_url = final_url or event.source_url
    origins: dict[str, Origin] = {
        "title": "source",
        "city": "inferred",
        "categories": "inferred",
    }
    if venue:
        origins["venue"] = "source"
    if start_date:
        origins["date"] = "source"
    if description:
        origins["description"] = "source"

    return Concert(
        source=event.source,
        source_id=event.source_id or source_id_from_url(source_url),
        source_url=source_url,
        title=title,
        event_name=title,
        description=description,
        date=start_date or event.date,
        end_date=end_date or event.end_date,
        start_time=None if all_day else (start_time or event.start_time),
        end_time=None if all_day else (end_time or event.end_time),
        all_day=all_day,
        timezone="Europe/Madrid",
        venue=venue or event.venue,
        city=city,
        province="A Coruña",
        country="ES",
        free=free if free else None,
        image_url=getattr(event, "image_url", None),
        categories=tipos,
        scraped_at=event.scraped_at,
        field_origins=origins,
    )
