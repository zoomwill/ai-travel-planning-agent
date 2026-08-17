"""Offline HTTP tests for the persistent POST SSE endpoint."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.routes import persistence as persistence_routes
from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from app.search.models import SearchKind
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.search.helpers import RecordingSearchBackend
from tests.streaming.test_service import FakeGraph, final_chunk, make_stream


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run the real graph with isolated in-memory saver/store and no Docker."""

    settings = Settings(_env_file=None, sse_heartbeat_seconds=0.01)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(
            lambda query: ["Tokyo photography and quiet-neighborhood context."]
        ),
    )
    with TestClient(application) as test_client:
        yield test_client


def payload(
    *,
    budget: str = "10000",
    destination: str = "Tokyo",
    remember: list[str] | None = None,
) -> dict[str, object]:
    """Reuse the exact persistent ThreadPlanRequest shape."""

    return {
        "user_id": "stream-user",
        "requirements": {
            "origin": "Shanghai",
            "destination": destination,
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
            "budget": budget,
            "currency": "CNY",
            "travelers": 1,
            "preferences": ["摄影", "quiet neighborhoods"],
        },
        "remember_preferences": remember or [],
    }


def parse_sse(text: str) -> tuple[list[dict[str, object]], list[str]]:
    """Parse the small SSE subset emitted by this endpoint for assertions."""

    events: list[dict[str, object]] = []
    comments: list[str] = []
    for frame in text.split("\n\n"):
        if not frame:
            continue
        fields: dict[str, str] = {}
        for line in frame.splitlines():
            if line.startswith(":"):
                comments.append(line[1:].strip())
                continue
            key, separator, value = line.partition(":")
            if separator:
                fields[key] = value.lstrip()
        if "data" in fields:
            event = json.loads(fields["data"])
            assert isinstance(event, dict)
            events.append(event)
            assert fields["id"] == str(event["event_id"])
            assert fields["event"] == event["event_type"]
    return events, comments


def test_stream_http_contract_progress_terminal_and_persistence(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agents/threads/http-stream-thread/plans/stream",
        json=payload(remember=["Quiet neighborhoods"]),
    )
    events, _comments = parse_sse(response.text)
    event_types = [event["event_type"] for event in events]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text.endswith("\n\n")
    first_frame = response.text.split("\n\n", maxsplit=1)[0]
    assert "id: 1" in first_frame.splitlines()
    assert "event: run_started" in first_frame.splitlines()
    assert any(line.startswith("data: ") for line in first_frame.splitlines())
    assert event_types[0] == "run_started"
    assert event_types.count("run_started") == 1
    assert event_types[-1] == "plan_completed"
    assert event_types.count("plan_completed") == 1
    assert "error" not in event_types
    assert "retrieval_completed" in event_types
    assert "review_completed" in event_types
    ids = [event["event_id"] for event in events]
    sequences = [event["sequence"] for event in events]
    assert ids == sequences == list(range(1, len(events) + 1))
    search_starts = {
        event["data"]["search_kind"] for event in events if event["event_type"] == "search_started"
    }
    search_terminals = {
        event["data"]["search_kind"]
        for event in events
        if event["event_type"] in {"search_completed", "search_failed"}
    }
    assert search_starts == {"flights", "hotels", "attractions", "weather", "route"}
    assert search_terminals == search_starts
    final_plan = events[-1]["data"]["travel_plan"]
    assert final_plan["requirements"]["destination"] == "Tokyo"
    assert "摄影" in final_plan["requirements"]["preferences"]

    state = client.get("/api/v1/agents/threads/http-stream-thread/state")
    history = client.get("/api/v1/agents/threads/http-stream-thread/history?limit=3")
    preferences = client.get("/api/v1/users/stream-user/preferences")
    assert state.status_code == 200
    assert state.json()["status"] == "complete"
    assert state.json()["search_result_count"] == 5
    assert state.json()["travel_plan"] == final_plan
    assert history.status_code == 200 and history.json()["checkpoints"]
    assert [item["value"] for item in preferences.json()] == ["Quiet neighborhoods"]


def test_same_thread_second_stream_returns_paris_instead_of_stale_tokyo(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/v1/agents/threads/reused-stream-thread/plans/stream",
        json=payload(destination="Tokyo"),
    )
    second = client.post(
        "/api/v1/agents/threads/reused-stream-thread/plans/stream",
        json=payload(destination="Paris"),
    )
    first_events, _ = parse_sse(first.text)
    second_events, _ = parse_sse(second.text)

    assert first_events[-1]["event_type"] == "plan_completed"
    assert first_events[-1]["data"]["travel_plan"]["requirements"]["destination"] == "Tokyo"
    assert second_events[-1]["event_type"] == "plan_completed"
    assert second_events[-1]["data"]["travel_plan"]["requirements"]["destination"] == "Paris"
    state = client.get("/api/v1/agents/threads/reused-stream-thread/state")
    assert state.status_code == 200
    assert state.json()["travel_plan"]["requirements"]["destination"] == "Paris"


def test_invalid_identifiers_and_body_fail_before_sse_headers(client: TestClient) -> None:
    bad_thread = client.post(
        "/api/v1/agents/threads/bad%20thread/plans/stream",
        json=payload(),
    )
    bad_body = client.post(
        "/api/v1/agents/threads/good-thread/plans/stream",
        json={"user_id": "stream-user"},
    )

    assert bad_thread.status_code == 422
    assert bad_thread.headers["content-type"].startswith("application/json")
    assert bad_thread.json()["detail"]["code"] == "invalid_thread_id"
    assert bad_body.status_code == 422
    assert bad_body.headers["content-type"].startswith("application/json")


def test_uninitialized_mcp_backend_fails_before_stream_starts() -> None:
    settings = Settings(_env_file=None, travel_search_backend_mode="mcp")
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/mcp-preflight/plans/stream",
            json=payload(),
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"]["code"] == "stream_backend_unavailable"
    assert "run_started" not in response.text
    assert all(secret not in response.text for secret in ("traceback", "command", "env", "9001"))


def test_idle_http_stream_frames_comment_heartbeat_without_consuming_sequence() -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    delayed_stream = make_stream(
        FakeGraph([final_chunk()], delay_seconds=0.03),
        heartbeat=0.005,
    )
    application.dependency_overrides[persistence_routes._prepare_plan_stream] = lambda: (
        persistence_routes._PreparedPlanStream(stream=delayed_stream)
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/heartbeat-thread/plans/stream",
            json=payload(),
        )

    events, comments = parse_sse(response.text)
    assert comments
    assert set(comments) == {"ping"}
    assert [event["sequence"] for event in events] == [1, 2]
    assert events[-1]["event_type"] == "plan_completed"
    assert response.text.rstrip().endswith("id: 2")


def test_natural_low_budget_stream_emits_real_revision_cycle(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agents/threads/revision-stream/plans/stream",
        json=payload(budget="1000"),
    )
    events, _ = parse_sse(response.text)
    event_types = [event["event_type"] for event in events]
    reviews = [event for event in events if event["event_type"] == "review_completed"]

    assert response.status_code == 200
    assert len(reviews) >= 2
    assert reviews[0]["data"]["decision"] == "revise"
    assert "revision_started" in event_types
    assert event_types[-1] == "plan_completed"
    assert event_types.count("plan_completed") == 1


def test_runtime_search_failure_is_one_safe_terminal_sse_error() -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(
            search_backend=RecordingSearchBackend(fail_kind=SearchKind.FLIGHTS)
        ),
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/failed-stream/plans/stream",
            json=payload(),
        )
    events, _ = parse_sse(response.text)
    event_types = [event["event_type"] for event in events]

    assert response.status_code == 200
    assert event_types[-1] == "error"
    assert event_types.count("error") == 1
    assert "plan_completed" not in event_types
    assert events[-1]["data"]["error_code"] == "critical_search_failed"
    assert all(
        secret not in response.text
        for secret in ("private backend detail", "traceback", "postgresql://", "Bearer")
    )
