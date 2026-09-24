import httpx
import respx

from src.http.client import HttpClient


@respx.mock
def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.http.client.time.sleep", lambda _: None)
    route = respx.get("https://example.test/agenda").mock(
        side_effect=[
            httpx.Response(503, text="no"),
            httpx.Response(200, text="<html>ok</html>"),
        ]
    )
    client = HttpClient(
        timeout=1,
        retries=3,
        backoff_seconds=0,
        user_agent="galicia-concert-agent/0.1 (+local-batch)",
        delay=0,
    )
    assert client.get_text("https://example.test/agenda") == "<html>ok</html>"
    assert route.call_count == 2
    client.close()
