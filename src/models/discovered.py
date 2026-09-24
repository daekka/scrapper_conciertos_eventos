from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from datetime import time as Time
from typing import Literal

from pydantic import BaseModel, Field

Origin = Literal["source", "inferred", "enriched"]


class DiscoveredEvent(BaseModel):
    """Datos baratos obtenidos de la vista mensual, sin ficha de detalle."""

    source: str
    event_id: str | None = None
    instance_id: str | None = None
    source_id: str
    source_url: str
    detail_url: str
    title: str
    venue: str | None = None
    city: str | None = None
    date: Date | None = None
    end_date: Date | None = None
    start_time: Time | None = None
    end_time: Time | None = None
    all_day: bool = False
    ticket_url: str | None = None
    category_label: str | None = None
    scraped_at: DateTime


class Concert(BaseModel):
    """Evento completo tras ficha de detalle (y, más adelante, enrichment)."""

    source: str
    source_id: str
    source_url: str
    title: str
    artist: str | None = None
    event_name: str | None = None
    description: str | None = None
    date: Date | None = None
    end_date: Date | None = None
    start_time: Time | None = None
    end_time: Time | None = None
    all_day: bool = False
    timezone: str = "Europe/Madrid"
    venue: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    price: float | None = None
    currency: str | None = None
    free: bool | None = None
    image_url: str | None = None
    ticket_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    published_at: DateTime | None = None
    modified_at: DateTime | None = None
    scraped_at: DateTime
    field_origins: dict[str, Origin] = Field(default_factory=dict)
    listing_fingerprint: str | None = None
