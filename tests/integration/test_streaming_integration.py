"""Opt-in real persistence, RAG, direct, and MCP SSE tests for P12."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.main import create_app
from tests.api.test_streaming import parse_sse, payload

pytestmark = pytest.mark.integration
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_INTEGRATION_ENABLED = os.getenv("RUN_INTEGRATION_TESTS") == "1"


def _free_port() -> int:
    """Reserve and release a loopback port for one test subprocess."""

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int, timeout_seconds: float = 5) -> None:
    """Wait a bounded time for the local HTTP MCP Server to listen."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError("HTTP MCP subprocess did not bind its dynamic port")


@pytest.fixture
def running_http_mcp() -> Iterator[int]:
    """Start one real HTTP MCP Server and always reap it within five seconds."""

    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.mcp_tools.servers.travel_http",
            "--port",
            str(port),
        ],
        cwd=_PROJECT_ROOT,
        env={
            "PYTHONPATH": str(_PROJECT_ROOT),
            "PYTHONUNBUFFERED": "1",
            "TRAVEL_DATA_MODE": "demo",
            "AGENT_REASONING_MODE": "deterministic",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield port
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        assert process.poll() is not None


async def _delete_threads(settings: Settings, *thread_ids: str) -> None:
    """Delete only UUID-scoped checkpoints created by this test module."""

    async with AsyncPostgresSaver.from_conn_string(
        settings.langgraph_postgres_uri.get_secret_value(),
        serde=create_strict_serializer(),
    ) as saver:
        for thread_id in thread_ids:
            await saver.adelete_thread(thread_id)


def _assert_complete_stream(response_text: str) -> list[dict[str, object]]:
    """Validate common public invariants without assuming completion order."""

    events, _ = parse_sse(response_text)
    event_types = [event["event_type"] for event in events]
    assert event_types[0] == "run_started"
    assert event_types[-1] == "plan_completed"
    assert event_types.count("plan_completed") == 1
    assert "error" not in event_types
    starts = {
        event["data"]["search_kind"] for event in events if event["event_type"] == "search_started"
    }
    terminals = {
        event["data"]["search_kind"]
        for event in events
        if event["event_type"] in {"search_completed", "search_failed"}
    }
    assert starts == terminals == {"flights", "hotels", "attractions", "weather", "route"}
    assert "retrieval_completed" in event_types
    assert "review_completed" in event_types
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    TravelPlan.model_validate(events[-1]["data"]["travel_plan"])
    return events


@pytest.mark.skipif(not _INTEGRATION_ENABLED, reason="set RUN_INTEGRATION_TESTS=1")
def test_direct_stream_persists_revision_memory_and_survives_restart() -> None:
    """Real PostgreSQL/RAG direct streams persist both normal and revised plans."""

    settings = Settings(
        travel_search_backend_mode="direct",
        agent_reasoning_mode="deterministic",
    )
    unique = uuid4().hex
    normal_thread = f"p12-{unique}-direct"
    revision_thread = f"p12-{unique}-revision"
    user_id = f"p12-{unique}-user"
    remembered_id = ""
    try:
        with TestClient(create_app(settings=settings)) as client:
            normal_body = payload(remember=["Quiet neighborhoods"])
            normal_body["user_id"] = user_id
            normal = client.post(
                f"/api/v1/agents/threads/{normal_thread}/plans/stream",
                json=normal_body,
            )
            assert normal.status_code == 200
            assert normal.headers["content-type"].startswith("text/event-stream")
            _assert_complete_stream(normal.text)

            revision_body = payload(budget="1000")
            revision_body["user_id"] = user_id
            revision = client.post(
                f"/api/v1/agents/threads/{revision_thread}/plans/stream",
                json=revision_body,
            )
            revision_events = _assert_complete_stream(revision.text)
            review_decisions = [
                event["data"]["decision"]
                for event in revision_events
                if event["event_type"] == "review_completed"
            ]
            assert review_decisions[0] == "revise"
            assert "revision_started" in [event["event_type"] for event in revision_events]

            paris = client.post(
                f"/api/v1/agents/threads/{normal_thread}/plans/stream",
                json=payload(destination="Paris"),
            )
            paris_events = _assert_complete_stream(paris.text)
            assert paris_events[-1]["data"]["travel_plan"]["requirements"]["destination"] == (
                "Paris"
            )

            state = client.get(f"/api/v1/agents/threads/{normal_thread}/state")
            history = client.get(f"/api/v1/agents/threads/{normal_thread}/history")
            preferences = client.get(f"/api/v1/users/{user_id}/preferences")
            assert state.json()["status"] == "complete"
            assert state.json()["search_result_count"] == 5
            assert state.json()["retrieval_query_variant_count"] > 0
            assert state.json()["travel_plan"]["requirements"]["destination"] == "Paris"
            assert history.json()["checkpoints"]
            remembered_id = preferences.json()[0]["preference_id"]

        with TestClient(create_app(settings=settings)) as restarted:
            restored = restarted.get(f"/api/v1/agents/threads/{normal_thread}/state")
            assert restored.status_code == 200
            assert restored.json()["status"] == "complete"
            assert restored.json()["travel_plan"] is not None
            assert restored.json()["travel_plan"]["requirements"]["destination"] == "Paris"
            if remembered_id:
                deleted = restarted.delete(f"/api/v1/users/{user_id}/preferences/{remembered_id}")
                assert deleted.status_code == 204
    finally:
        asyncio.run(_delete_threads(settings, normal_thread, revision_thread))


@pytest.mark.skipif(not _INTEGRATION_ENABLED, reason="set RUN_INTEGRATION_TESTS=1")
def test_mcp_stream_succeeds_and_unavailable_server_is_preflight_503(
    running_http_mcp: int,
) -> None:
    """Real MCP transports stream once; a missing HTTP Server never falls back."""

    port = running_http_mcp
    unique = uuid4().hex
    thread_id = f"p12-{unique}-mcp"
    settings = Settings(
        _env_file=None,
        travel_search_backend_mode="mcp",
        mcp_http_port=port,
        mcp_http_url=f"http://127.0.0.1:{port}/mcp",
    )
    try:
        with TestClient(create_app(settings=settings)) as client:
            response = client.post(
                f"/api/v1/agents/threads/{thread_id}/plans/stream",
                json=payload(),
            )
            assert response.status_code == 200
            events = _assert_complete_stream(response.text)
            assert events[0]["data"]["backend_mode"] == "mcp"
            state = client.get(f"/api/v1/agents/threads/{thread_id}/state")
            assert state.json()["search_backend_mode"] == "mcp"
            assert all("ToolMessage" not in repr(value) for value in state.json().values())
    finally:
        asyncio.run(_delete_threads(settings, thread_id))

    unavailable_port = _free_port()
    unavailable_settings = Settings(
        _env_file=None,
        travel_search_backend_mode="mcp",
        mcp_http_port=unavailable_port,
        mcp_http_url=f"http://127.0.0.1:{unavailable_port}/mcp",
        mcp_discovery_timeout_seconds=1,
    )
    with TestClient(create_app(settings=unavailable_settings)) as unavailable_client:
        unavailable = unavailable_client.post(
            f"/api/v1/agents/threads/p12-{unique}-unavailable/plans/stream",
            json=payload(),
        )
    assert unavailable.status_code == 503
    assert unavailable.headers["content-type"].startswith("application/json")
    assert unavailable.json()["detail"]["code"] == "stream_backend_unavailable"
    assert all(
        secret not in unavailable.text
        for secret in ("traceback", "9001", "command", "Bearer", "postgresql://")
    )
