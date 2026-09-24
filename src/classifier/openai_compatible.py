from __future__ import annotations

import json
import logging

import httpx
from pydantic import ValidationError

from src.config import LlmCredentials
from src.errors import ClassificationInvalid, LLMError
from src.models.classification import ClassificationResult
from src.models.discovered import Concert

logger = logging.getLogger(__name__)


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


class OpenAICompatibleClassifier:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        completions_url: str,
        auth_style: str = "bearer",
        query: dict[str, str] | None = None,
        include_temperature: bool = True,
        timeout: float = 40,
    ) -> None:
        self.model = model
        self.completions_url = completions_url
        self.query = dict(query or {})
        self.include_temperature = include_temperature
        if auth_style == "api_key":
            headers = {"api-key": api_key, "Content-Type": "application/json"}
        elif auth_style == "bearer":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        else:
            raise ValueError(f"auth_style no soportado: {auth_style}")
        self._client = httpx.Client(timeout=timeout, headers=headers)

    @classmethod
    def from_openai(
        cls,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 40,
    ) -> OpenAICompatibleClassifier:
        return cls(
            api_key=api_key,
            model=model,
            completions_url=f"{base_url.rstrip('/')}/chat/completions",
            auth_style="bearer",
            include_temperature=True,
            timeout=timeout,
        )

    @classmethod
    def from_azure(
        cls,
        *,
        api_key: str,
        endpoint: str,
        api_version: str,
        deployment: str,
        timeout: float = 40,
    ) -> OpenAICompatibleClassifier:
        base = endpoint.rstrip("/")
        return cls(
            api_key=api_key,
            model=deployment,
            completions_url=(
                f"{base}/openai/deployments/{deployment}/chat/completions"
            ),
            auth_style="api_key",
            query={"api-version": api_version},
            include_temperature=False,
            timeout=timeout,
        )

    @classmethod
    def from_credentials(
        cls, credentials: LlmCredentials, *, timeout: float = 40
    ) -> OpenAICompatibleClassifier:
        if credentials.provider == "azure":
            if not (
                credentials.azure_endpoint
                and credentials.azure_api_version
                and credentials.azure_deployment
            ):
                raise LLMError("Credenciales Azure OpenAI incompletas")
            return cls.from_azure(
                api_key=credentials.api_key,
                endpoint=credentials.azure_endpoint,
                api_version=credentials.azure_api_version,
                deployment=credentials.azure_deployment,
                timeout=timeout,
            )
        if not credentials.base_url:
            raise LLMError("Falta OPENAI_BASE_URL para el proveedor OpenAI-compatible")
        return cls.from_openai(
            api_key=credentials.api_key,
            base_url=credentials.base_url,
            model=credentials.model,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def classify(self, concert: Concert, taste: str) -> ClassificationResult:
        payload = concert.model_dump(mode="json", exclude={"field_origins"})
        body: dict = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Clasifica un concierto según el perfil musical del usuario. "
                        "Responde solo JSON con las claves classification "
                        "(INTERESTED, MAYBE o IGNORE), confidence (número entre 0 y 1), "
                        "reason (texto breve), matched_preferences (lista de strings), "
                        "suggested_tags (lista de strings) y music_genres (lista de 1 a 3 "
                        "géneros/estilos musicales breves del artista o grupo, p. ej. "
                        '["rock", "hard rock"]; usa [] si no hay información suficiente; '
                        "no inventes). No inventes datos del concierto. "
                        "Si el perfil está vacío, sé conservador.\n\n"
                        + json.dumps(
                            {"taste": taste, "concert": payload},
                            ensure_ascii=False,
                        )
                    ),
                },
            ],
        }
        if self.include_temperature:
            body["temperature"] = 0
        try:
            response = self._client.post(
                self.completions_url,
                params=self.query or None,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"No se pudo contactar con el proveedor LLM: {exc}") from exc
        if response.status_code in {401, 403}:
            raise LLMError(f"El proveedor LLM rechazó la autenticación ({response.status_code})")
        if response.status_code >= 400:
            raise LLMError(
                f"El proveedor LLM respondió HTTP {response.status_code}: {response.text}"
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_fence(content))
            result = ClassificationResult.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            logger.error("Respuesta LLM inválida")
            raise ClassificationInvalid("La respuesta del clasificador no es válida") from exc
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            logger.info(
                "LLM usage: prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
        return result
