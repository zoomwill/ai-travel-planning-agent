"""Opt-in real STDIO and Streamable HTTP MCP transport test."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from app.core.config import Settings
from app.domain.models import Attraction, FlightOption, HotelOption, RouteSummary, WeatherSummary
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.mcp_tools.client import build_mcp_client, create_mcp_runtime
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.protocol import EXPECTED_TOOL_NAMES
from app.search.backend import DeterministicMockSearchBackend
from tests.graphs.test_persistence import make_state
from tests.mcp_tools.helpers import requirements

pytestmark = pytest.mark.integration
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int, timeout_seconds: float = 5) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError("HTTP MCP subprocess did not bind its dynamic port")


@pytest.fixture
def running_http_mcp() -> Iterator[tuple[int, subprocess.Popen[bytes]]]:
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
        yield port, process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        assert process.poll() is not None


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check real local MCP transports",
)
@pytest.mark.asyncio
async def test_real_mcp_transports_backend_graph_and_cleanup(
    running_http_mcp: tuple[int, subprocess.Popen[bytes]],
) -> None:
    port, http_process = running_http_mcp
    settings = Settings(
        _env_file=None,
        travel_search_backend_mode="mcp",
        mcp_http_port=port,
        mcp_http_url=f"http://127.0.0.1:{port}/mcp",
    )
    client = build_mcp_client(settings)

    local_tools = await client.get_tools(server_name="local_tools")
    travel_tools = await client.get_tools(server_name="travel_tools")
    all_tools = await client.get_tools()
    assert sorted(tool.name for tool in local_tools) == ["get_route", "get_weather"]
    assert sorted(tool.name for tool in travel_tools) == [
        "search_attractions",
        "search_flights",
        "search_hotels",
    ]
    assert sorted(tool.name for tool in all_tools) == list(EXPECTED_TOOL_NAMES)

    runtime = await create_mcp_runtime(settings)
    assert runtime.diagnostics.ready is True
    trip = requirements()
    assert all(
        isinstance(item, FlightOption) for item in await runtime.backend.search_flights(trip)
    )
    assert all(isinstance(item, HotelOption) for item in await runtime.backend.search_hotels(trip))
    assert all(
        isinstance(item, Attraction) for item in await runtime.backend.search_attractions(trip)
    )
    assert all(isinstance(item, WeatherSummary) for item in await runtime.backend.get_weather(trip))
    assert isinstance(await runtime.backend.get_route(trip.origin, trip.destination), RouteSummary)

    graph = build_travel_planning_graph(
        lambda query: ["P10 context remains available."],
        search_backend=runtime.backend,
    )
    graph_result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="p11-integration"),
    )
    assert len(graph_result["search_results"]) == 5
    assert graph_result["review_status"] == "accepted"
    assert graph_result["retrieved_context"] == ["P10 context remains available."]
    assert all("Client" not in repr(value) for value in graph_result.values())

    direct_graph = build_travel_planning_graph(
        lambda query: [], search_backend=DeterministicMockSearchBackend()
    )
    direct_result = await direct_graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="p11-direct"),
    )
    assert direct_result["travel_plan"] is not None

    http_process.terminate()
    http_process.wait(timeout=5)
    with pytest.raises(MCPToolLayerError) as stopped:
        await runtime.backend.search_flights(trip)
    assert stopped.value.error_type == "mcp_transport_unavailable"

    invalid_stdio = MultiServerMCPClient(
        {
            "invalid": cast(
                Connection,
                {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "app.mcp_tools.servers.module_does_not_exist"],
                    "cwd": str(_PROJECT_ROOT),
                    "env": {"PYTHONUNBUFFERED": "1"},
                },
            )
        }
    )
    with pytest.raises(BaseExceptionGroup):
        await invalid_stdio.get_tools()
