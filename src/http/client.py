from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpRequestError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float,
        retries: int,
        backoff_seconds: float,
        user_agent: str,
        delay: float = 0.0,
    ) -> None:
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff_seconds = backoff_seconds
        self.delay = delay
        self._last_request = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        response = self._request("GET", url, headers=headers or None)
        if response.status_code >= 400:
            raise HttpRequestError(
                f"HTTP {response.status_code} en {url}",
                status_code=response.status_code,
            )
        return response.text

    def request_json(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self._request(method, url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        # httpx no acepta headers=None
        if kwargs.get("headers") is None:
            kwargs.pop("headers", None)
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("HTTP %s %s intento %s falló: %s", method, url, attempt, exc)
            else:
                if response.status_code in _RETRY_STATUS and attempt < self.retries:
                    logger.warning(
                        "HTTP %s %s respondió %s; reintento %s",
                        method,
                        url,
                        response.status_code,
                        attempt,
                    )
                    self._sleep_backoff(attempt)
                    continue
                return response
            self._sleep_backoff(attempt)
        raise HttpRequestError(f"No se pudo completar {method} {url}: {last_error}")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
