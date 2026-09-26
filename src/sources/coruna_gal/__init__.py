"""Fuente de eventos de ocio/cultura de A Coruña (RSS coruna.gal)."""

from src.sources.coruna_gal.source import CorunaGalSource
from src.sources.coruna_gal.tipos import (
    KEY_TO_LABEL,
    OTROS_KEY,
    TIPO_KEYS,
    infer_tipos,
    primary_list_key,
    tipo_keys_from_labels,
)

__all__ = [
    "CorunaGalSource",
    "KEY_TO_LABEL",
    "OTROS_KEY",
    "TIPO_KEYS",
    "infer_tipos",
    "primary_list_key",
    "tipo_keys_from_labels",
]
