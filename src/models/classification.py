from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.normalize.genres import MAX_MUSIC_GENRES, normalize_music_genres


class ClassificationResult(BaseModel):
    classification: Literal["INTERESTED", "MAYBE", "IGNORE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    matched_preferences: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    music_genres: list[str] = Field(default_factory=list)

    @field_validator("music_genres", mode="before")
    @classmethod
    def _coerce_music_genres(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return normalize_music_genres(value)[:MAX_MUSIC_GENRES]
