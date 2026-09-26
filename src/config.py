from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class SourceSettings:
    name: str
    base_url: str
    agenda_path: str
    months_ahead: int
    request_delay: float
    timeout: float
    retries: int
    backoff_seconds: float


@dataclass
class Settings:
    timezone: str
    user_agent: str
    source: SourceSettings
    classification_enabled: bool
    lists: dict[str, str]
    geo_lists: dict[str, str]
    base_tags: list[str]
    allow_suggested: list[str]
    past_retention_days: int = 7
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)

    @property
    def taste_path(self) -> Path:
        return self.project_root / "config" / "taste.md"

    @property
    def all_list_names(self) -> dict[str, str]:
        return {**self.lists, **self.geo_lists}


CORUNA_LIST_KEYS: tuple[str, ...] = ("ocio", "past")

OCIO_LIST_KEY = "ocio"


@dataclass
class CorunaSettings:
    """Pipeline aislado de ocio/cultura Coruña (una lista activa + pasados)."""

    timezone: str
    user_agent: str
    feed_url: str
    request_delay: float
    timeout: float
    retries: int
    backoff_seconds: float
    lists: dict[str, str]
    base_tags: list[str] = field(default_factory=list)
    allow_suggested: list[str] = field(default_factory=list)
    past_retention_days: int = 7
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)

    @property
    def all_list_names(self) -> dict[str, str]:
        return dict(self.lists)

    @property
    def active_list_keys(self) -> frozenset[str]:
        """Claves de listas activas (sin past)."""
        return frozenset(k for k in self.lists if k != "past")


def load_settings(root: Path | None = None) -> Settings:
    project_root = (root or PROJECT_ROOT).resolve()
    load_dotenv(project_root / ".env")
    path = project_root / "config" / "settings.yaml"
    if not path.is_file():
        raise ConfigError(f"No se encuentra la configuración: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        source_raw = raw["source"]
        karakeep_raw = raw["karakeep"]
        lists = karakeep_raw["lists"]
        geo_raw = karakeep_raw.get("geo_lists") or {}
        tags = raw.get("tags") or {}
        retention = int(karakeep_raw.get("past_retention_days", 7))
        if retention < 0:
            raise ConfigError("karakeep.past_retention_days debe ser >= 0")
        geo_lists = {
            "geo_acoruna": str(geo_raw["geo_acoruna"]),
            "geo_vigo": str(geo_raw["geo_vigo"]),
            "geo_santiago": str(geo_raw["geo_santiago"]),
            "geo_ourense": str(geo_raw["geo_ourense"]),
            "geo_lugo": str(geo_raw["geo_lugo"]),
            "geo_pontevedra": str(geo_raw["geo_pontevedra"]),
            "geo_ferrol": str(geo_raw["geo_ferrol"]),
            "geo_other": str(geo_raw["geo_other"]),
        }
        settings = Settings(
            timezone=str(raw["timezone"]),
            user_agent=str(raw["user_agent"]),
            source=SourceSettings(
                name=str(source_raw["name"]),
                base_url=str(source_raw["base_url"]).rstrip("/"),
                agenda_path=str(source_raw["agenda_path"]),
                months_ahead=int(source_raw["months_ahead"]),
                request_delay=float(source_raw["request_delay"]),
                timeout=float(source_raw["timeout"]),
                retries=int(source_raw["retries"]),
                backoff_seconds=float(source_raw["backoff_seconds"]),
            ),
            classification_enabled=bool(raw["classification"]["enabled"]),
            lists={
                "interested": str(lists["interested"]),
                "maybe": str(lists["maybe"]),
                "ignored": str(lists["ignored"]),
                "past": str(lists["past"]),
            },
            geo_lists=geo_lists,
            base_tags=[str(t) for t in tags.get("base", [])],
            allow_suggested=[str(t) for t in tags.get("allow_suggested", [])],
            past_retention_days=retention,
            project_root=project_root,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"config/settings.yaml inválido: {exc}") from exc
    return settings


def load_coruna_settings(root: Path | None = None) -> CorunaSettings:
    """Carga el pipeline ``pipelines.coruna`` (lista única + pasados, sin geo)."""
    project_root = (root or PROJECT_ROOT).resolve()
    load_dotenv(project_root / ".env")
    path = project_root / "config" / "settings.yaml"
    if not path.is_file():
        raise ConfigError(f"No se encuentra la configuración: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        pipelines = raw.get("pipelines") or {}
        coruna_raw = pipelines["coruna"]
        lists_raw = coruna_raw["lists"]
        tags = coruna_raw.get("tags") or {}
        retention = int(coruna_raw.get("past_retention_days", 7))
        if retention < 0:
            raise ConfigError("pipelines.coruna.past_retention_days debe ser >= 0")
        lists = {key: str(lists_raw[key]) for key in CORUNA_LIST_KEYS}
        return CorunaSettings(
            timezone=str(raw["timezone"]),
            user_agent=str(raw["user_agent"]),
            feed_url=str(coruna_raw["feed_url"]).strip(),
            request_delay=float(coruna_raw.get("request_delay", 1.0)),
            timeout=float(coruna_raw.get("timeout", 20)),
            retries=int(coruna_raw.get("retries", 3)),
            backoff_seconds=float(coruna_raw.get("backoff_seconds", 1.5)),
            lists=lists,
            base_tags=[str(t) for t in tags.get("base", [])],
            allow_suggested=[str(t) for t in tags.get("allow_suggested", [])],
            past_retention_days=retention,
            project_root=project_root,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"pipelines.coruna inválido en settings.yaml: {exc}") from exc


def karakeep_credentials() -> tuple[str, str]:
    url = os.environ.get("KARAKEEP_URL", "").strip().rstrip("/")
    key = os.environ.get("KARAKEEP_API_KEY", "").strip()
    if not url or not key:
        raise ConfigError("Faltan KARAKEEP_URL o KARAKEEP_API_KEY en el entorno")
    return url, key


@dataclass(frozen=True)
class LlmCredentials:
    """Credenciales del clasificador. provider es azure u openai."""

    provider: str
    api_key: str
    model: str
    base_url: str | None = None
    azure_endpoint: str | None = None
    azure_api_version: str | None = None
    azure_deployment: str | None = None


def llm_credentials() -> LlmCredentials:
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "").strip()
    azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    azure_parts = {
        "AZURE_OPENAI_ENDPOINT": azure_endpoint,
        "AZURE_OPENAI_API_VERSION": azure_api_version,
        "AZURE_OPENAI_DEPLOYMENT": azure_deployment,
        "AZURE_OPENAI_API_KEY": azure_key,
    }
    present = [name for name, value in azure_parts.items() if value]
    if present and len(present) < len(azure_parts):
        missing = [name for name, value in azure_parts.items() if not value]
        raise ConfigError(
            "Configuración Azure OpenAI incompleta; faltan: " + ", ".join(missing)
        )
    if len(present) == len(azure_parts):
        return LlmCredentials(
            provider="azure",
            api_key=azure_key,
            model=azure_deployment,
            azure_endpoint=azure_endpoint,
            azure_api_version=azure_api_version,
            azure_deployment=azure_deployment,
        )

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not key or not model:
        raise ConfigError(
            "Faltan credenciales LLM: configura Azure OpenAI completo "
            "o OPENAI_API_KEY y OPENAI_MODEL"
        )
    return LlmCredentials(
        provider="openai",
        api_key=key,
        model=model,
        base_url=base.rstrip("/"),
    )


def openai_credentials() -> tuple[str, str, str]:
    """Compatibilidad: solo proveedor OpenAI-compatible (sin Azure)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not key or not model:
        raise ConfigError("Faltan OPENAI_API_KEY u OPENAI_MODEL en el entorno")
    return key, base.rstrip("/"), model
