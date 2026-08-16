"""API behavior for direct, ready MCP, and unavailable MCP modes."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import readiness as readiness_module
from app.core.config import Settings
from app.core.resources import AppResources
from app.graphs.graph import build_travel_planning_graph
from app.main import create_app
from app.mcp_tools.backend import MCPTravelSearchBackend, UnavailableMCPTravelSearchBackend
from app.mcp_tools.client import MCPRuntime
from app.mcp_tools.diagnostics import MCPDiagnostics, MCPServerStatus
from tests.api.test_agent_plans import valid_payload
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.mcp_tools.test_backend_graph import ProviderInvoker


class FakeMCPRuntime:
    """Expose only the public readiness and diagnostics used by API routes."""

    def __init__(self, *, ready: bool) -> None:
        self.diagnostics = MCPDiagnostics(
            backend_mode="mcp",
            initialized=True,
            ready=ready,
            servers={
                "local_tools": MCPServerStatus(
                    transport="stdio", ready=ready, tools=["get_route", "get_weather"]
                ),
                "travel_tools": MCPServerStatus(
                    transport="http",
                    ready=ready,
                    tools=["search_attractions", "search_flights", "search_hotels"],
                ),
            },
            expected_tools=[
                "get_route",
                "get_weather",
                "search_attractions",
                "search_flights",
                "search_hotels",
            ],
            discovered_tools=[
                "get_route",
                "get_weather",
                "search_attractions",
                "search_flights",
                "search_hotels",
            ],
            expected_tool_count=5,
            discovered_tool_count=5,
        )

    async def is_ready(self) -> bool:
        return self.diagnostics.ready


@contextmanager
def _client(
    settings: Settings,
    *,
    backend=None,
    runtime: FakeMCPRuntime | None = None,
) -> Iterator[TestClient]:
    fakes = make_resource_fakes(settings)
    fakes.resources.search_backend = backend
    fakes.resources.mcp_runtime = cast(MCPRuntime, runtime)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
        travel_graph=(
            build_travel_planning_graph(lambda query: [], search_backend=backend)
            if backend is not None
            else None
        ),
    )
    with TestClient(application) as test_client:
        yield test_client


def test_status_direct_mode_is_explicit() -> None:
    with _client(Settings(_env_file=None)) as client:
        response = client.get("/api/v1/mcp/status")

    assert response.status_code == 200
    assert response.json()["backend_mode"] == "direct"
    assert response.json()["initialized"] is False
    assert response.json()["ready"] is True


def test_mcp_ready_status_and_agent_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock(return_value=None))
    settings = Settings(_env_file=None, travel_search_backend_mode="mcp")
    runtime = FakeMCPRuntime(ready=True)
    backend = MCPTravelSearchBackend(ProviderInvoker())

    with _client(settings, backend=backend, runtime=runtime) as client:
        status = client.get("/api/v1/mcp/status")
        ready = client.get("/ready")
        plan = client.post("/api/v1/agents/plans", json=valid_payload())
        persistent = client.post(
            "/api/v1/agents/threads/mcp-api-thread/plans",
            json={
                "user_id": "mcp-api-user",
                "requirements": valid_payload(),
                "remember_preferences": [],
            },
        )
        state = client.get("/api/v1/agents/threads/mcp-api-thread/state")

    assert status.json()["discovered_tool_count"] == 5
    assert ready.status_code == 200
    assert ready.json()["services"]["mcp"] == {"status": "ok"}
    assert plan.status_code == 200
    assert persistent.status_code == 200
    assert persistent.json()["search_backend_mode"] == "mcp"
    assert state.json()["search_backend_mode"] == "mcp"


def test_mcp_failure_keeps_health_alive_and_returns_safe_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock(return_value=None))
    settings = Settings(_env_file=None, travel_search_backend_mode="mcp")

    with _client(settings, backend=UnavailableMCPTravelSearchBackend()) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        plan = client.post("/api/v1/agents/plans", json=valid_payload())
        status = client.get("/api/v1/mcp/status")

    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["services"]["mcp"] == {"status": "error"}
    assert plan.status_code == 503
    assert status.json()["last_error_type"] == "mcp_discovery_failed"
    assert all(secret not in plan.text for secret in ("traceback", "command", "env", "9001"))
