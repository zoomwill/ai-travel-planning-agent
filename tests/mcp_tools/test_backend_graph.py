"""Offline MCP backend and LangGraph compatibility tests."""

import asyncio
from typing import cast

import pytest

from app.domain.models import Attraction, FlightOption, HotelOption, WeatherSummary
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.mcp_tools.backend import MCPTravelSearchBackend
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.models import MCPToolRequest, MCPToolResponse, failed_response
from app.search.models import JsonValue, dump_model_json
from app.services import mock_providers
from tests.graphs.test_persistence import make_state
from tests.mcp_tools.helpers import requirements


class ProviderInvoker:
    """Return existing provider data through the same MCP envelope boundary."""

    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
        self.calls.append(tool_name)
        domain = request.requirements.to_domain()
        if tool_name == "search_flights":
            data = [dump_model_json(item) for item in mock_providers.search_flights(domain)]
        elif tool_name == "search_hotels":
            data = [dump_model_json(item) for item in mock_providers.search_hotels(domain)]
        elif tool_name == "search_attractions":
            data = [dump_model_json(item) for item in mock_providers.search_attractions(domain)]
        elif tool_name == "get_weather":
            data = [dump_model_json(item) for item in mock_providers.get_weather(domain)]
        else:
            return failed_response(request, "get_route")
        return MCPToolResponse(
            ok=True,
            tool_name=tool_name,
            task_id=request.task_id,
            request_fingerprint=request.request_fingerprint,
            data=cast(JsonValue, data),
        )


class BarrierProviderInvoker(ProviderInvoker):
    """Release tool calls only after all five graph branches have entered."""

    def __init__(self) -> None:
        super().__init__()
        self.entered: set[str] = set()
        self.all_entered = asyncio.Event()

    async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
        self.entered.add(tool_name)
        if len(self.entered) == 5:
            self.all_entered.set()
        await asyncio.wait_for(self.all_entered.wait(), timeout=1)
        return await super().invoke(tool_name, request)


@pytest.mark.asyncio
async def test_backend_maps_all_five_results_to_existing_domain_models() -> None:
    invoker = ProviderInvoker()
    backend = MCPTravelSearchBackend(invoker)
    trip = requirements()

    flights = await backend.search_flights(trip)
    hotels = await backend.search_hotels(trip)
    attractions = await backend.search_attractions(trip)
    weather = await backend.get_weather(trip)
    with pytest.raises(MCPToolLayerError):
        await backend.get_route(trip.origin, trip.destination)

    assert all(isinstance(item, FlightOption) for item in flights)
    assert all(isinstance(item, HotelOption) for item in hotels)
    assert all(isinstance(item, Attraction) for item in attractions)
    assert all(isinstance(item, WeatherSummary) for item in weather)
    assert sorted(invoker.calls) == [
        "get_route",
        "get_weather",
        "search_attractions",
        "search_flights",
        "search_hotels",
    ]


@pytest.mark.asyncio
async def test_backend_rejects_invalid_domain_output() -> None:
    class InvalidInvoker:
        async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
            return MCPToolResponse(
                ok=True,
                tool_name=tool_name,
                task_id=request.task_id,
                request_fingerprint=request.request_fingerprint,
                data=[{"flight_number": "missing-fields"}],
            )

    with pytest.raises(MCPToolLayerError) as captured:
        await MCPTravelSearchBackend(InvalidInvoker()).search_flights(requirements())
    assert captured.value.error_type == "mcp_invalid_response"


@pytest.mark.asyncio
async def test_backend_rejects_mismatched_task_metadata() -> None:
    class MismatchedInvoker(ProviderInvoker):
        async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
            response = await super().invoke(tool_name, request)
            return response.model_copy(update={"task_id": "different-task"})

    with pytest.raises(MCPToolLayerError) as captured:
        await MCPTravelSearchBackend(MismatchedInvoker()).search_flights(requirements())
    assert captured.value.error_type == "mcp_invalid_response"


@pytest.mark.asyncio
async def test_backend_normalizes_generic_provider_failure() -> None:
    """Keep generic MCP failures inside the stable internal error vocabulary."""

    class FailedInvoker:
        async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
            return failed_response(request, tool_name)

    with pytest.raises(MCPToolLayerError) as captured:
        await MCPTravelSearchBackend(FailedInvoker()).search_flights(requirements())
    assert captured.value.error_type == "mcp_tool_failed"


@pytest.mark.asyncio
async def test_graph_keeps_parallel_search_review_rag_and_json_safe_state() -> None:
    invoker = ProviderInvoker()
    graph = build_travel_planning_graph(
        lambda query: ["MCP graph retrieval context."],
        search_backend=MCPTravelSearchBackend(invoker),
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="mcp-unit-user"),
    )

    assert result["travel_plan"] is not None
    assert len(result["search_results"]) == 4
    assert len({item["task_id"] for item in result["search_results"]}) == 4
    assert result["search_summary"]["route"]["status"] == "error"
    assert sorted(invoker.calls) == [
        "get_route",
        "get_weather",
        "search_attractions",
        "search_flights",
        "search_hotels",
    ]
    assert result["review_status"] == "accepted"
    assert result["retrieved_context"] == ["MCP graph retrieval context."]
    assert all("Client" not in repr(value) for value in result.values())


@pytest.mark.asyncio
async def test_graph_enters_all_five_mcp_calls_before_any_can_finish() -> None:
    invoker = BarrierProviderInvoker()
    graph = build_travel_planning_graph(
        lambda query: [],
        search_backend=MCPTravelSearchBackend(invoker),
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="mcp-barrier-user"),
    )

    assert len(invoker.entered) == 5
    assert len(result["search_results"]) == 4
    assert len(result["search_tasks"]) == 5
