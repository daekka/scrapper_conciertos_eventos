from datetime import datetime, timezone
import json

import httpx
import respx

from src.classifier.openai_compatible import OpenAICompatibleClassifier
from src.config import LlmCredentials, llm_credentials
from src.errors import ClassificationInvalid, ConfigError, LLMError
from src.models.discovered import Concert


def _concert() -> Concert:
    return Concert(
        source="galicia_en_concierto",
        source_id="1:1",
        source_url="https://galiciaenconcierto.com/evento/x/",
        title="X",
        scraped_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"classification":"IGNORE","confidence":0.2,'
                            '"reason":"No encaja.","matched_preferences":[],'
                            '"suggested_tags":[]}'
                        )
                    }
                }
            ]
        },
    )


def _request_json(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


@respx.mock
def test_classifier_parses_music_genres_in_same_call():
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"classification":"INTERESTED","confidence":0.9,'
                                '"reason":"Rock.","matched_preferences":["rock"],'
                                '"suggested_tags":["rock"],'
                                '"music_genres":["rock","hard rock"]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    result = client.classify(_concert(), "perfil")
    assert result.music_genres == ["rock", "hard rock"]
    assert len(route.calls) == 1
    body = _request_json(route.calls.last.request)
    assert "music_genres" in body["messages"][0]["content"]
    client.close()


@respx.mock
def test_classifier_missing_music_genres_defaults_empty():
    respx.post("https://llm.test/v1/chat/completions").mock(return_value=_ok_response())
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    result = client.classify(_concert(), "perfil")
    assert result.music_genres == []
    client.close()


@respx.mock
def test_openai_compatible_sends_temperature_zero():
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=_ok_response()
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    client.classify(_concert(), "perfil")
    body = _request_json(route.calls.last.request)
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    client.close()


@respx.mock
def test_azure_classifier_omits_temperature():
    url = (
        "https://example.openai.azure.com/openai/deployments/"
        "gpt-6-luna/chat/completions"
    )
    route = respx.post(url).mock(return_value=_ok_response())
    client = OpenAICompatibleClassifier.from_azure(
        api_key="azure-secret",
        endpoint="https://example.openai.azure.com",
        api_version="2024-08-01-preview",
        deployment="gpt-6-luna",
    )
    result = client.classify(_concert(), "perfil")
    assert result.classification == "IGNORE"
    request = route.calls.last.request
    body = _request_json(request)
    assert "temperature" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert request.headers["api-key"] == "azure-secret"
    assert "authorization" not in {key.lower() for key in request.headers.keys()}
    assert request.url.params["api-version"] == "2024-08-01-preview"
    assert body["model"] == "gpt-6-luna"
    client.close()


@respx.mock
def test_from_credentials_prefers_azure_without_temperature():
    url = (
        "https://example.openai.azure.com/openai/deployments/"
        "deploy-a/chat/completions"
    )
    route = respx.post(url).mock(return_value=_ok_response())
    credentials = LlmCredentials(
        provider="azure",
        api_key="azure-secret",
        model="deploy-a",
        azure_endpoint="https://example.openai.azure.com",
        azure_api_version="2024-02-15-preview",
        azure_deployment="deploy-a",
    )
    client = OpenAICompatibleClassifier.from_credentials(credentials)
    assert client.classify(_concert(), "").classification == "IGNORE"
    body = _request_json(route.calls.last.request)
    assert "temperature" not in body
    assert route.calls.last.request.headers["api-key"] == "azure-secret"
    client.close()


@respx.mock
def test_from_credentials_openai_fallback_sends_temperature():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_response()
    )
    credentials = LlmCredentials(
        provider="openai",
        api_key="sk-test",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
    )
    client = OpenAICompatibleClassifier.from_credentials(credentials)
    assert client.classify(_concert(), "").classification == "IGNORE"
    body = _request_json(route.calls.last.request)
    assert body["temperature"] == 0
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"
    client.close()


def test_llm_credentials_selects_azure(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ignored")
    monkeypatch.setenv("OPENAI_MODEL", "ignored")
    credentials = llm_credentials()
    assert credentials.provider == "azure"
    assert credentials.azure_endpoint == "https://example.openai.azure.com"
    assert credentials.azure_deployment == "gpt-4o-mini"
    assert credentials.api_key == "azure-secret"


def test_llm_credentials_falls_back_to_openai(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    credentials = llm_credentials()
    assert credentials.provider == "openai"
    assert credentials.base_url == "https://llm.test/v1"
    assert credentials.model == "m"


def test_llm_credentials_rejects_partial_azure(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    try:
        llm_credentials()
        raise AssertionError("debía fallar")
    except ConfigError as exc:
        assert "AZURE_OPENAI_API_VERSION" in str(exc)
        assert "AZURE_OPENAI_DEPLOYMENT" in str(exc)


@respx.mock
def test_classifier_rejects_invalid_payload():
    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"classification":"NOPE"}'}}]},
        )
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    try:
        client.classify(_concert(), "perfil")
        raise AssertionError("debía fallar")
    except ClassificationInvalid:
        pass
    finally:
        client.close()


@respx.mock
def test_classifier_auth_failure_is_provider_error():
    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "no"})
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    try:
        client.classify(_concert(), "perfil")
        raise AssertionError("debía fallar")
    except LLMError as exc:
        assert "autenticación" in str(exc)
    finally:
        client.close()


def _ok_response_with_usage() -> httpx.Response:
    payload = _ok_response().json()
    payload["usage"] = {
        "prompt_tokens": 120,
        "completion_tokens": 45,
        "total_tokens": 165,
    }
    return httpx.Response(200, json=payload)


@respx.mock
def test_openai_logs_usage_on_success(caplog):
    import logging

    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=_ok_response_with_usage()
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    caplog.set_level(logging.INFO)
    assert client.classify(_concert(), "perfil").classification == "IGNORE"
    assert (
        "LLM usage: prompt_tokens=120 completion_tokens=45 total_tokens=165"
        in caplog.text
    )
    assert "perfil" not in caplog.text
    assert "Bearer" not in caplog.text
    client.close()


@respx.mock
def test_azure_logs_usage_on_success(caplog):
    import logging

    url = (
        "https://example.openai.azure.com/openai/deployments/"
        "gpt-6-luna/chat/completions"
    )
    respx.post(url).mock(return_value=_ok_response_with_usage())
    client = OpenAICompatibleClassifier.from_azure(
        api_key="azure-secret",
        endpoint="https://example.openai.azure.com",
        api_version="2024-08-01-preview",
        deployment="gpt-6-luna",
    )
    caplog.set_level(logging.INFO)
    assert client.classify(_concert(), "perfil").classification == "IGNORE"
    assert (
        "LLM usage: prompt_tokens=120 completion_tokens=45 total_tokens=165"
        in caplog.text
    )
    assert "azure-secret" not in caplog.text
    client.close()


@respx.mock
def test_missing_usage_does_not_fail(caplog):
    import logging

    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=_ok_response()
    )
    client = OpenAICompatibleClassifier.from_openai(
        api_key="k", base_url="https://llm.test/v1", model="m"
    )
    caplog.set_level(logging.INFO)
    assert client.classify(_concert(), "perfil").classification == "IGNORE"
    assert "LLM usage:" not in caplog.text
    client.close()
