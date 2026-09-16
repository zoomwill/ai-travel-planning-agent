"""Data-mode, fallback, MCP parity, concurrency, and grounding regression tests."""

import asyncio
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from app.core.persistence import create_strict_serializer
from app.domain.models import TravelDataSource, TravelPlan
from app.external.duffel.backend import DuffelTravelSearchBackend
from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient
from app.external.duffel.errors import DuffelError
from app.external.duffel.flights import DuffelFlightProvider
from app.external.duffel.locations import DuffelLocationResolver, ResolvedLocation
from app.external.duffel.stays import DuffelStayProvider
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.mcp_tools.backend import MCPTravelSearchBackend
from app.mcp_tools.models import MCPToolRequest, MCPToolResponse
from app.search.models import JsonValue, SearchKind, dump_model_json
from app.services.mock_providers import search_flights, search_hotels
from app.services.mock_providers.route_provider import RouteUnavailableError
from tests.external.duffel.helpers import make_client, offer, place, requirements, stay_result
from tests.graphs.test_persistence import make_state


class Resolver:
    """Resolve the two fixture cities without another HTTP operation."""

    async def resolve(self, query: str) -> ResolvedLocation:
        code = "CLE" if query == "Cleveland" else "TYO"
        return ResolvedLocation(query, "US", query, code, (code,), 35.0, 139.0)


def make_backend(handler, *, fallback: bool = False) -> tuple[DuffelTravelSearchBackend, object]:
    """Build a test-mode external bundle around one MockTransport."""

    client = make_client(handler, max_retries=0)
    resolver = Resolver()
    backend = DuffelTravelSearchBackend(
        flights=DuffelFlightProvider(
            client,
            resolver,  # type: ignore[arg-type]
            max_offers=5,
            source=TravelDataSource.DUFFEL_TEST,
        ),
        stays=DuffelStayProvider(
            client,
            resolver,  # type: ignore[arg-type]
            max_results=10,
            source=TravelDataSource.DUFFEL_TEST,
        ),
        source=TravelDataSource.DUFFEL_TEST,
        allow_demo_fallback=fallback,
    )
    return backend, client


@pytest.mark.asyncio
async def test_duffel_mode_is_external_for_two_kinds_and_demo_for_three() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/air/offer_requests":
            return httpx.Response(200, json={"data": {"offers": [offer()]}})
        return httpx.Response(200, json={"data": {"results": [stay_result()]}})

    backend, client = make_backend(handler)
    trip = requirements()
    results = {
        SearchKind.FLIGHTS: await backend.search_flights(trip),
        SearchKind.HOTELS: await backend.search_hotels(trip),
        SearchKind.ATTRACTIONS: await backend.search_attractions(trip),
        SearchKind.WEATHER: await backend.get_weather(trip),
    }
    with pytest.raises(RouteUnavailableError):
        await backend.get_route(trip.origin, trip.destination)
    await client.aclose()  # type: ignore[attr-defined]

    assert {kind: values[0].data_source for kind, values in results.items()} == {
        SearchKind.FLIGHTS: TravelDataSource.DUFFEL_TEST,
        SearchKind.HOTELS: TravelDataSource.DUFFEL_TEST,
        SearchKind.ATTRACTIONS: TravelDataSource.DEMO,
        SearchKind.WEATHER: TravelDataSource.DEMO,
    }


@pytest.mark.asyncio
async def test_no_silent_fallback_and_explicit_fallback_label() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"errors": []})

    strict, strict_client = make_backend(handler)
    with pytest.raises(DuffelError):
        await strict.search_flights(requirements())
    await strict_client.aclose()  # type: ignore[attr-defined]

    fallback, fallback_client = make_backend(handler, fallback=True)
    flights = await fallback.search_flights(requirements())
    hotels = await fallback.search_hotels(requirements())
    await fallback_client.aclose()  # type: ignore[attr-defined]
    assert all(item.data_source is TravelDataSource.DEMO_FALLBACK for item in flights)
    assert all(item.data_source is TravelDataSource.DEMO_FALLBACK for item in hotels)


@pytest.mark.asyncio
async def test_mcp_round_trip_preserves_duffel_domain_result() -> None:
    direct_flights = [
        item.model_copy(update={"data_source": TravelDataSource.DUFFEL_TEST})
        for item in search_flights(requirements())
    ]

    class Invoker:
        async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
            return MCPToolResponse(
                ok=True,
                tool_name=tool_name,
                task_id=request.task_id,
                request_fingerprint=request.request_fingerprint,
                data=cast(JsonValue, [dump_model_json(item) for item in direct_flights]),
                provider="duffel",
                source=TravelDataSource.DUFFEL_TEST,
            )

    mcp_results = await MCPTravelSearchBackend(
        Invoker(),
        TravelDataSource.DUFFEL_TEST,
    ).search_flights(requirements())
    assert mcp_results == direct_flights


@pytest.mark.asyncio
async def test_external_flight_and_stay_branches_enter_concurrently() -> None:
    entered: set[str] = set()
    both_entered = asyncio.Event()

    class FlightProvider:
        async def search(self, trip):
            entered.add("flights")
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            return [
                item.model_copy(update={"data_source": TravelDataSource.DUFFEL_TEST})
                for item in search_flights(trip)
            ]

    class StayProvider:
        async def search(self, trip):
            entered.add("hotels")
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            return [
                item.model_copy(update={"data_source": TravelDataSource.DUFFEL_TEST})
                for item in search_hotels(trip)
            ]

    backend = DuffelTravelSearchBackend(
        flights=FlightProvider(),  # type: ignore[arg-type]
        stays=StayProvider(),  # type: ignore[arg-type]
        source=TravelDataSource.DUFFEL_TEST,
    )
    graph = build_travel_planning_graph(lambda _: [], search_backend=backend)
    state = make_state()
    trip = requirements()
    state["requirements"] = trip
    state["user_request"] = "Plan Cleveland to Tokyo"
    result = await graph.ainvoke(
        state,
        context=TravelRuntimeContext(user_id="duffel-parallel"),
    )

    assert entered == {"flights", "hotels"}
    assert result["travel_plan"] is not None
    assert result["search_summary"]["flights"]["source"] == "duffel_test"
    assert result["search_summary"]["hotels"]["source"] == "duffel_test"


@pytest.mark.asyncio
async def test_fake_http_full_graph_preserves_mixed_sources_and_strict_messagepack() -> None:
    """Exercise real request/mapping code in one graph without internet or quota."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/places/suggestions":
            query = request.url.params["query"]
            value = (
                place("Cleveland", "CLE", latitude=41.5, longitude=-81.7)
                if query == "Cleveland"
                else place("Tokyo", "TYO", latitude=35.67, longitude=139.65)
            )
            return httpx.Response(200, json={"data": [value]})
        if request.url.path == "/air/offer_requests":
            return httpx.Response(200, json={"data": {"offers": [offer()]}})
        if request.url.path == "/stays/search":
            return httpx.Response(200, json={"data": {"results": [stay_result()]}})
        raise AssertionError(f"unexpected path: {request.url.path}")

    http_client = httpx.AsyncClient(
        base_url=DUFFEL_API_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    client = DuffelClient(
        http_client,
        access_token=SecretStr("unit-only-token"),
        environment="test",
        api_version="v2",
        timeout_seconds=20,
        max_retries=0,
    )
    resolver = DuffelLocationResolver(client)
    backend = DuffelTravelSearchBackend(
        flights=DuffelFlightProvider(
            client,
            resolver,
            max_offers=5,
            source=TravelDataSource.DUFFEL_TEST,
        ),
        stays=DuffelStayProvider(
            client,
            resolver,
            max_results=10,
            source=TravelDataSource.DUFFEL_TEST,
        ),
        source=TravelDataSource.DUFFEL_TEST,
    )
    graph = build_travel_planning_graph(lambda _: [], search_backend=backend)
    state = make_state()
    state["requirements"] = requirements()
    state["user_request"] = "Plan Cleveland to Tokyo"
    result = await graph.ainvoke(
        state,
        context=TravelRuntimeContext(user_id="duffel-fake-http"),
    )
    await client.aclose()

    plan = TravelPlan.model_validate(result["travel_plan"])
    assert plan.data_sources.model_dump(mode="json") == {
        "flights": "duffel_test",
        "hotels": "duffel_test",
        "attractions": "demo",
        "weather": "demo",
        "route": "demo",
    }
    serialized = create_strict_serializer().dumps_typed(result)
    restored = create_strict_serializer().loads_typed(serialized)
    restored_plan = TravelPlan.model_validate(restored["travel_plan"])
    assert restored_plan.data_sources.flights is TravelDataSource.DUFFEL_TEST
    assert "Authorization" not in repr(restored)
    assert "unit-only-token" not in repr(restored)
