"""Offline transport, retry, header, and redaction tests for DuffelClient."""

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient
from app.external.duffel.errors import DuffelError
from tests.external.duffel.helpers import make_client


@pytest.mark.asyncio
async def test_headers_content_type_and_timeout_are_explicit() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, max_retries=0)
    await client.post("/air/offer_requests", json={"data": {}}, operation="flight_offer_request")
    await client.aclose()

    request = captured["request"]
    assert request.url.host == "api.duffel.com"
    assert request.headers["authorization"] == "Bearer unit-only-token"
    assert request.headers["duffel-version"] == "v2"
    assert request.headers["content-type"] == "application/json"
    assert request.extensions["timeout"]["read"] == 20


@pytest.mark.asyncio
async def test_request_log_contains_only_safe_bounded_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def capture(event: str, _: str, **fields: Any) -> None:
        events.append((event, fields))

    monkeypatch.setattr("app.external.duffel.client.log_event", capture)
    client = make_client(
        lambda _: httpx.Response(200, json={"data": {"offers": [{}, {}]}}),
        max_retries=0,
    )
    await client.post("/air/offer_requests", json={"data": {}}, operation="flight_offer_request")
    await client.aclose()

    event, fields = events[0]
    assert event == "external_request_completed"
    assert fields["status"] == "success"
    assert fields["result_count"] == 2
    assert isinstance(fields["duration_ms"], float)
    assert "unit-only-token" not in repr(events)
    assert "Authorization" not in repr(events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "duffel_authentication_failed"),
        (403, "duffel_stays_access_denied"),
        (400, "duffel_provider_error"),
    ],
)
async def test_non_retryable_http_errors_are_stable(status_code: int, expected_code: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"errors": [{"message": "private"}]})

    client = make_client(handler)
    with pytest.raises(DuffelError) as captured:
        await client.post("/stays/search", json={"data": {}}, operation="stay_search")
    await client.aclose()

    assert captured.value.code == expected_code
    assert calls == 1
    assert "private" not in str(captured.value)
    assert "unit-only-token" not in repr(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503, 504])
async def test_retryable_status_retries_once(status_code: int) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, headers={"ratelimit-reset": "0"})
        return httpx.Response(200, json={"data": {}})

    async def fake_sleep(value: float) -> None:
        sleeps.append(value)

    client = make_client(handler, sleep=fake_sleep)
    assert await client.get(
        "/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup"
    ) == {"data": {}}
    await client.aclose()
    assert calls == 2
    assert len(sleeps) == 1 and 0 <= sleeps[0] <= 2


@pytest.mark.asyncio
async def test_500_is_not_retried_per_current_official_guidance() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"errors": []})

    client = make_client(handler)
    with pytest.raises(DuffelError, match="duffel_provider_error"):
        await client.get(
            "/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup"
        )
    await client.aclose()
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (httpx.ReadTimeout("late"), "duffel_timeout"),
        (httpx.ConnectError("reset"), "duffel_transport_error"),
    ],
)
async def test_transport_failures_use_bounded_retry(
    exception: Exception, expected_code: str
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception

    client = make_client(handler, sleep=lambda _: asyncio.sleep(0))
    with pytest.raises(DuffelError) as captured:
        await client.get(
            "/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup"
        )
    await client.aclose()
    assert captured.value.code == expected_code
    assert calls == 2


@pytest.mark.asyncio
async def test_malformed_json_is_rejected_without_retry() -> None:
    client = make_client(
        lambda _: httpx.Response(200, content=b"not-json", headers={"content-type": "text/plain"})
    )
    with pytest.raises(DuffelError, match="duffel_invalid_response"):
        await client.get(
            "/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup"
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_cancellation_propagates_unchanged() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client = make_client(handler)
    with pytest.raises(asyncio.CancelledError):
        await client.get(
            "/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup"
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_client_rejects_any_non_official_base_url() -> None:
    untrusted = httpx.AsyncClient(base_url="https://example.com")
    with pytest.raises(ValueError, match="fixed official API host"):
        DuffelClient(
            untrusted,
            access_token=SecretStr("unit-only-token"),
            environment="test",
            api_version="v2",
            timeout_seconds=20,
            max_retries=1,
        )
    await untrusted.aclose()
    assert DUFFEL_API_BASE_URL == "https://api.duffel.com"
