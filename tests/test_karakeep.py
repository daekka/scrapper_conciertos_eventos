from datetime import date, datetime, time, timezone
from pathlib import Path

import httpx
import respx

from src.http.client import HttpClient
from src.storage.karakeep import KaraKeepClient
from src.storage.models import BookmarkTag, KnownBookmark

LISTS = {
    "interested": "🎵 Conciertos · Interesan",
    "maybe": "🤔 Conciertos · Quizá",
    "ignored": "🚫 Conciertos · Descartados",
    "past": "📦 Conciertos · Pasados",
}
BASE = "https://karakeep.test"
BANNER = Path(__file__).parent / "fixtures" / "concert-default.png"
EVENT_URL = "https://galiciaenconcierto.com/evento/banda/"


def _client(**kwargs) -> KaraKeepClient:
    http = HttpClient(timeout=2, retries=1, backoff_seconds=0, user_agent="test", delay=0)
    client = KaraKeepClient(
        base_url=BASE,
        api_key="secret-key",
        list_names=LISTS,
        http=http,
        default_banner_path=BANNER,
        crawl_poll_seconds=0,
        crawl_timeout_seconds=kwargs.pop("crawl_timeout_seconds", 60.0),
        **kwargs,
    )
    client._sleep = lambda _seconds: None
    return client


def _seed_lists(client: KaraKeepClient) -> None:
    client._list_ids = {
        "interested": "list-1",
        "maybe": "list-2",
        "ignored": "list-3",
        "past": "list-4",
    }


def _create_payload(*, status: int = 201, bookmark_id: str = "bm-1"):
    return httpx.Response(
        status,
        json={
            "id": bookmark_id,
            "title": "Banda",
            "note": "nota",
            "content": {"type": "link", "url": EVENT_URL, "crawlStatus": "pending"},
            "tags": [],
            "assets": [],
        },
    )


def _bookmark_get(
    *,
    crawl_status: str,
    assets: list[dict] | None = None,
    image_asset_id: str | None = None,
    bookmark_id: str = "bm-1",
):
    content = {
        "type": "link",
        "url": EVENT_URL,
        "crawlStatus": crawl_status,
    }
    if image_asset_id is not None:
        content["imageAssetId"] = image_asset_id
    return httpx.Response(
        200,
        json={
            "id": bookmark_id,
            "title": "Banda",
            "note": "nota",
            "content": content,
            "tags": [],
            "assets": assets or [],
        },
    )


def _mock_create(*, status: int = 201, bookmark_id: str = "bm-1"):
    return respx.post(f"{BASE}/api/v1/bookmarks").mock(
        return_value=_create_payload(status=status, bookmark_id=bookmark_id)
    )


def _mock_tags_and_list(bookmark_id: str = "bm-1"):
    respx.post(f"{BASE}/api/v1/bookmarks/{bookmark_id}/tags").mock(
        return_value=httpx.Response(200, json={"attached": ["tag-1"]})
    )
    respx.put(f"{BASE}/api/v1/lists/list-1/bookmarks/{bookmark_id}").mock(
        return_value=httpx.Response(204)
    )


def _mock_upload(asset_id: str = "asset-new"):
    return respx.post(f"{BASE}/api/v1/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "assetId": asset_id,
                "contentType": "image/png",
                "size": BANNER.stat().st_size,
                "fileName": "concert-default.png",
            },
        )
    )


def _create_with_crawl(
    *,
    crawl_responses: list[httpx.Response],
    assets_after: list[dict],
    image_asset_id: str | None = None,
):
    _mock_create()
    _mock_tags_and_list()
    get_route = respx.get(f"{BASE}/api/v1/bookmarks/bm-1").mock(
        side_effect=[
            *crawl_responses,
            _bookmark_get(
                crawl_status="success",
                assets=assets_after,
                image_asset_id=image_asset_id,
            ),
        ]
    )
    return get_route


@respx.mock
def test_create_sends_concert_created_at_and_keeps_banner_flow():
    create_route = _mock_create()
    _mock_tags_and_list()
    # Timeout inmediato: no hay recrawl/banner; solo validamos createdAt en el POST.
    client = _client(crawl_timeout_seconds=0)
    _seed_lists(client)
    created_at = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    bookmark = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
        created_at=created_at,
    )
    body = create_route.calls.last.request.content.decode()
    assert '"createdAt":"2026-09-25T20:00:00.000Z"' in body
    assert '"crawlPriority":"low"' in body
    assert bookmark.id == "bm-1"
    assert not any(call.request.method == "PATCH" for call in respx.calls)
    client.http.close()


@respx.mock
def test_set_created_at_patches_only_that_field():
    patch = respx.patch(f"{BASE}/api/v1/bookmarks/bm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "bm-1",
                "createdAt": "2026-09-25T20:00:00.000Z",
                "title": "Banda",
                "note": "nota",
                "content": {"type": "link", "url": EVENT_URL},
                "tags": [],
            },
        )
    )
    client = _client()
    bookmark = KnownBookmark(
        id="bm-1",
        url=EVENT_URL,
        title="Banda",
        note="nota original",
        tags=[BookmarkTag(name="concert", attached_by="ai")],
        list_keys={"interested"},
        created_at=datetime(2026, 9, 23, 20, 42, 42, tzinfo=timezone.utc),
    )
    note_before = bookmark.note
    tags_before = list(bookmark.tags)
    lists_before = set(bookmark.list_keys)
    action = client.set_created_at(
        bookmark, datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    )
    assert action == "updated"
    assert patch.calls.last.request.content.decode() == '{"createdAt":"2026-09-25T20:00:00.000Z"}'
    assert bookmark.note == note_before
    assert bookmark.tags == tags_before
    assert bookmark.list_keys == lists_before
    assert bookmark.created_at == datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    assert client.set_created_at(bookmark, bookmark.created_at) == "noop"
    assert patch.call_count == 1
    client.http.close()


@respx.mock
def test_crawl_success_attaches_banner_when_none_exists():
    get_route = _create_with_crawl(
        crawl_responses=[
            _bookmark_get(crawl_status="pending"),
            _bookmark_get(crawl_status="success", assets=[]),
            _bookmark_get(crawl_status="success", assets=[]),
        ],
        assets_after=[{"id": "asset-new", "assetType": "bannerImage", "fileName": "concert-default.png"}],
        image_asset_id="asset-new",
    )
    upload = _mock_upload()
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(
            201,
            json={"id": "asset-new", "assetType": "bannerImage"},
        )
    )
    replace = respx.put(url__regex=r".*/bookmarks/bm-1/assets/.+").mock(
        return_value=httpx.Response(204)
    )

    client = _client()
    _seed_lists(client)
    bookmark = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    assert bookmark.id == "bm-1"
    assert upload.call_count == 1
    assert attach.call_count == 1
    assert replace.call_count == 0
    assert get_route.call_count >= 3
    assert "multipart/form-data" in upload.calls.last.request.headers["content-type"]
    assert b'"assetType":"bannerImage"' in attach.calls.last.request.content
    client.http.close()


@respx.mock
def test_crawl_success_replaces_existing_banner():
    crawler_banner = {"id": "asset-crawler", "assetType": "bannerImage", "fileName": None}
    get_route = _create_with_crawl(
        crawl_responses=[
            _bookmark_get(crawl_status="pending"),
            _bookmark_get(
                crawl_status="success",
                assets=[crawler_banner],
                image_asset_id="asset-crawler",
            ),
            _bookmark_get(
                crawl_status="success",
                assets=[crawler_banner],
                image_asset_id="asset-crawler",
            ),
        ],
        assets_after=[{"id": "asset-new", "assetType": "bannerImage", "fileName": "concert-default.png"}],
        image_asset_id="asset-new",
    )
    upload = _mock_upload("asset-new")
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(201, json={"id": "asset-new", "assetType": "bannerImage"})
    )
    replace = respx.put(f"{BASE}/api/v1/bookmarks/bm-1/assets/asset-crawler").mock(
        return_value=httpx.Response(204)
    )

    client = _client()
    _seed_lists(client)
    assert client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    ).id == "bm-1"
    assert upload.call_count == 1
    assert replace.call_count == 1
    assert attach.call_count == 0
    assert b'"assetId":"asset-new"' in replace.calls.last.request.content
    assert get_route.call_count >= 3
    client.http.close()


@respx.mock
def test_crawl_failure_still_applies_banner(caplog):
    import logging

    _create_with_crawl(
        crawl_responses=[
            _bookmark_get(crawl_status="pending"),
            _bookmark_get(crawl_status="failure", assets=[]),
            _bookmark_get(crawl_status="failure", assets=[]),
        ],
        assets_after=[{"id": "asset-new", "assetType": "bannerImage"}],
        image_asset_id="asset-new",
    )
    upload = _mock_upload()
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(201, json={"id": "asset-new", "assetType": "bannerImage"})
    )

    client = _client()
    _seed_lists(client)
    caplog.set_level(logging.INFO)
    assert client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    ).id == "bm-1"
    assert upload.call_count == 1
    assert attach.call_count == 1
    assert "Crawler falló" in caplog.text
    client.http.close()


@respx.mock
def test_crawl_timeout_skips_banner(caplog):
    import logging

    _mock_create()
    _mock_tags_and_list()
    get_route = respx.get(f"{BASE}/api/v1/bookmarks/bm-1").mock(
        return_value=_bookmark_get(crawl_status="pending")
    )
    upload = _mock_upload()
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(201, json={"id": "asset-new", "assetType": "bannerImage"})
    )

    client = _client(crawl_timeout_seconds=0)
    _seed_lists(client)
    caplog.set_level(logging.WARNING)
    bookmark = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    assert bookmark.id == "bm-1"
    assert upload.call_count == 0
    assert attach.call_count == 0
    assert get_route.call_count >= 1
    assert "Timeout esperando crawlStatus" in caplog.text
    client.http.close()


@respx.mock
def test_existing_bookmark_does_not_upload_banner():
    _mock_create(status=200)
    _mock_tags_and_list()
    get_route = respx.get(f"{BASE}/api/v1/bookmarks/bm-1").mock(
        return_value=_bookmark_get(crawl_status="success")
    )
    upload = _mock_upload()

    client = _client()
    _seed_lists(client)
    assert client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    ).id == "bm-1"
    assert upload.call_count == 0
    assert get_route.call_count == 0
    client.http.close()


@respx.mock
def test_update_does_not_touch_banner():
    client = _client()
    _seed_lists(client)
    respx.patch(f"{BASE}/api/v1/bookmarks/bm-existing").mock(
        return_value=httpx.Response(200, json={"id": "bm-existing"})
    )
    upload = _mock_upload("should-not")
    from src.storage.models import BookmarkTag, KnownBookmark

    bookmark = KnownBookmark(
        id="bm-existing",
        url=EVENT_URL,
        title="Banda",
        note="previa",
        tags=[BookmarkTag(name="concert", attached_by="human")],
        list_keys={"interested"},
    )
    client.update(bookmark, title="Banda", note="nueva", tags=[("concert", "ai")])
    assert upload.call_count == 0
    client.http.close()


@respx.mock
def test_replace_failure_keeps_created_bookmark(caplog):
    import logging

    _create_with_crawl(
        crawl_responses=[
            _bookmark_get(
                crawl_status="success",
                assets=[{"id": "asset-crawler", "assetType": "bannerImage"}],
                image_asset_id="asset-crawler",
            ),
            _bookmark_get(
                crawl_status="success",
                assets=[{"id": "asset-crawler", "assetType": "bannerImage"}],
                image_asset_id="asset-crawler",
            ),
        ],
        assets_after=[{"id": "asset-crawler", "assetType": "bannerImage"}],
        image_asset_id="asset-crawler",
    )
    upload = _mock_upload("asset-new")
    replace = respx.put(f"{BASE}/api/v1/bookmarks/bm-1/assets/asset-crawler").mock(
        return_value=httpx.Response(500, json={"error": "replace-fail"})
    )

    client = _client()
    _seed_lists(client)
    caplog.set_level(logging.ERROR)
    bookmark = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    assert bookmark.id == "bm-1"
    assert upload.call_count == 1
    assert replace.call_count == 1
    assert "Fallo al asegurar banner del bookmark" in caplog.text
    client.http.close()


@respx.mock
def test_attach_failure_keeps_created_bookmark(caplog):
    import logging

    _create_with_crawl(
        crawl_responses=[
            _bookmark_get(crawl_status="success", assets=[]),
            _bookmark_get(crawl_status="success", assets=[]),
        ],
        assets_after=[],
    )
    upload = _mock_upload("asset-new")
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(500, json={"error": "attach-fail"})
    )

    client = _client()
    _seed_lists(client)
    caplog.set_level(logging.ERROR)
    bookmark = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    assert bookmark.id == "bm-1"
    assert upload.call_count == 1
    assert attach.call_count == 1
    assert "Fallo al asegurar banner del bookmark" in caplog.text
    client.http.close()


@respx.mock
def test_retry_after_banner_failure_does_not_recreate_bookmark():
    create_route = respx.post(f"{BASE}/api/v1/bookmarks").mock(
        side_effect=[
            _create_payload(status=201),
            _create_payload(status=200),
        ]
    )
    _mock_tags_and_list()
    respx.get(f"{BASE}/api/v1/bookmarks/bm-1").mock(
        return_value=_bookmark_get(crawl_status="success", assets=[])
    )
    upload = respx.post(f"{BASE}/api/v1/assets").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    attach = respx.post(f"{BASE}/api/v1/bookmarks/bm-1/assets").mock(
        return_value=httpx.Response(201, json={"id": "asset-new", "assetType": "bannerImage"})
    )

    client = _client()
    _seed_lists(client)
    first = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    second = client.create(
        url=EVENT_URL,
        title="Banda",
        note="nota",
        tags=[("concert", "ai")],
        list_key="interested",
    )
    assert first.id == second.id == "bm-1"
    assert create_route.call_count == 2
    assert upload.call_count == 1
    assert attach.call_count == 0
    client.http.close()


@respx.mock
def test_index_without_create_missing_does_not_post_lists():
    client = _client()
    respx.get(f"{BASE}/api/v1/lists").mock(return_value=httpx.Response(200, json={"lists": []}))
    created = respx.post(f"{BASE}/api/v1/lists").mock(
        return_value=httpx.Response(201, json={"id": "should-not", "name": "x", "icon": "📁"})
    )
    assert client.index(create_missing=False) == {}
    assert created.call_count == 0
    client.http.close()


@respx.mock
def test_check_url_miss_returns_none():
    client = _client()
    respx.get(f"{BASE}/api/v1/bookmarks/check-url").mock(
        return_value=httpx.Response(200, json={"bookmarkId": None})
    )
    assert client.lookup_url("https://galiciaenconcierto.com/evento/no/") is None
    client.http.close()


def test_price_line_and_note_roundtrip():
    from src.models.classification import ClassificationResult
    from src.models.discovered import Concert
    from src.storage.bookmark_note import build_note, extract_analysis, parse_meta, parse_stored_concert

    concert = Concert(
        source="galicia_en_concierto",
        source_id="1:2",
        source_url="https://galiciaenconcierto.com/evento/banda/",
        title="Banda",
        artist="Banda",
        date=date(2026, 12, 1),
        start_time=time(21, 0),
        timezone="Europe/Madrid",
        venue="Sala",
        city="Vigo",
        province="Pontevedra",
        free=False,
        price=15,
        currency="EUR",
        scraped_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        listing_fingerprint="abc123",
        field_origins={"artist": "inferred"},
    )
    result = ClassificationResult(
        classification="MAYBE",
        confidence=0.5,
        reason="Puede encajar.",
        matched_preferences=["pop"],
        suggested_tags=[],
    )
    note = build_note(concert, result, pending=False)
    assert "💰 **Precio:** 15 €" in note
    assert parse_meta(note)["listing_fp"] == "abc123"
    restored = parse_stored_concert(note)
    assert restored is not None
    assert restored.city == "Vigo"
    preserved = extract_analysis(note)
    updated = build_note(
        concert.model_copy(update={"venue": "Otra"}),
        None,
        pending=False,
        preserved_analysis=preserved,
        classification_name="MAYBE",
    )
    assert "Otra" in updated
    assert "Puede encajar." in updated
    assert parse_meta(updated)["classification"] == "MAYBE"
