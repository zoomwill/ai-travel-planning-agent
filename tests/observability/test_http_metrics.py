"""Pure ASGI middleware and registry behavior tests."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from starlette.types import Message, Receive, Scope, Send

from app.core.config import Settings
from app.main import create_app
from app.observability.context import get_request_id
from app.observability.metrics import MetricsRuntime, normalize_label
from app.observability.middleware import ObservabilityMiddleware
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


def _client() -> tuple[TestClient, MetricsRuntime]:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resources(_: Settings):
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resources,
        persistence_factory=make_in_memory_persistence_factory(),
    )

    @application.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @application.get("/boom")
    async def boom(_: Request) -> None:
        raise RuntimeError("private traceback Token=hidden")

    return TestClient(application, raise_server_exceptions=False), application.state.metrics


def test_registry_is_isolated_and_labels_are_allowlisted() -> None:
    first = MetricsRuntime.create()
    second = MetricsRuntime.create()
    first.graph_runs.labels(backend="direct", status="success").inc()
    assert b'travel_planner_graph_runs_total{backend="direct",status="success"} 1.0' in (
        generate_latest(first.registry)
    )
    assert b"travel_planner_graph_runs_total{" not in generate_latest(second.registry)
    assert normalize_label("private-dynamic-value", frozenset({"safe"})) == "unknown"


def test_request_id_route_template_404_and_safe_500() -> None:
    client, metrics = _client()
    with client:
        matched = client.get("/items/raw-private-id", headers={"X-Request-ID": "caller-123"})
        missing = client.get("/not-a-real-route")
        failed = client.get("/boom", headers={"X-Request-ID": "invalid request id"})

    assert matched.headers["x-request-id"] == "caller-123"
    assert matched.json() == {"item_id": "raw-private-id"}
    assert missing.status_code == 404
    assert failed.status_code == 500
    assert failed.headers["x-request-id"] != "invalid request id"
    assert "private traceback" not in failed.text

    text = generate_latest(metrics.registry).decode()
    assert 'route="/items/{item_id}"' in text
    assert 'route="unmatched"' in text
    assert "raw-private-id" not in text
    assert "invalid request id" not in text


def test_metrics_content_type_and_scrape_does_not_self_instrument() -> None:
    client, _ = _client()
    with client:
        first = client.get("/metrics")
        second = client.get("/metrics")

    assert first.status_code == 200
    assert first.headers["content-type"] == "text/plain; version=1.0.0; charset=utf-8"
    assert second.status_code == 200
    assert 'route="/metrics"' not in second.text
    assert "/metrics/" not in second.headers.get("location", "")


def _asgi_scope(request_id: bytes) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/safe",
        "raw_path": b"/safe",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"x-request-id", request_id)],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "route": SimpleNamespace(path="/safe"),
    }


@pytest.mark.asyncio
async def test_non_ascii_request_id_is_rejected_instead_of_sanitized() -> None:
    metrics = MetricsRuntime.create()
    sent: list[Message] = []

    async def application(_: Scope, __: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = ObservabilityMiddleware(application, metrics)
    await middleware(_asgi_scope(b"caller\xff-id"), receive, send)

    response_start = next(item for item in sent if item["type"] == "http.response.start")
    returned_ids = [
        value for name, value in response_start["headers"] if name.lower() == b"x-request-id"
    ]
    assert len(returned_ids) == 1
    assert returned_ids[0] != b"caller-id"
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_cancelled_final_send_records_disconnect_and_restores_gauge() -> None:
    metrics = MetricsRuntime.create()

    async def application(_: Scope, __: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"complete"})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise asyncio.CancelledError

    middleware = ObservabilityMiddleware(application, metrics)
    with pytest.raises(asyncio.CancelledError):
        await middleware(_asgi_scope(b"safe-id"), receive, send)

    text = generate_latest(metrics.registry).decode()
    assert 'status_code="499"' in text
    assert 'travel_planner_http_requests_in_progress{method="GET"} 0.0' in text
    assert get_request_id() is None
