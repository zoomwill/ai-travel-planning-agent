"""Cross-layer regressions using mock HTTP, real graph, and strict checkpoints."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from prometheus_client import generate_latest
from pydantic import ValidationError

from app.api.routes import readiness as readiness_module
from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.domain.models import TravelDataSource, TravelPlan
from app.external.backend import configured_sources
from app.external.duffel.client import DUFFEL_API_BASE_URL
from app.external.liteapi.client import LITEAPI_BASE_URL
from app.external.liteapi.errors import LiteAPIError
from app.external.runtime import create_travel_runtime
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.intake.models import IntakeStatus
from app.intake.service import ConversationIntakeService
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.grounding import stable_candidate_id
from app.mcp_tools.backend import MCPTravelSearchBackend
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.models import MCPToolRequest
from app.mcp_tools.servers import travel_http
from app.memory.preferences import list_user_preferences
from app.observability.metrics import MetricsRuntime
from app.search.models import SearchKind
from tests.api.test_streaming import parse_sse
from tests.external.duffel.helpers import offer as flight_offer
from tests.external.duffel.helpers import place
from tests.external.duffel.test_api import _client
from tests.external.liteapi.helpers import FAKE_KEY, payload, response, trip
from tests.graphs.test_persistence import make_state
from tests.intake.test_service import extraction


def settings(**updates):
    return Settings(
        _env_file=None,
        **{
            "travel_data_mode": "external",
            "duffel_access_token": "duffel_test_unit_only",
            "liteapi_api_key": FAKE_KEY,
            "duffel_max_retries": 0,
            "liteapi_max_retries": 0,
            **updates,
        },
    )


@pytest.mark.parametrize(
    "mode,hotel,expected",
    [
        ("demo", "liteapi", "demo"),
        ("external", "liteapi", "liteapi_sandbox"),
        ("external", "duffel_stays", "duffel_test"),
        ("duffel", "liteapi", "duffel_test"),
        ("external", "demo", "demo"),
    ],
)
def test_provider_selection_and_legacy_alias(mode, hotel, expected):
    configuration = settings(travel_data_mode=mode, travel_hotel_provider=hotel)
    sources = configured_sources(configuration)
    assert sources[SearchKind.HOTELS].value == expected
    assert sources[SearchKind.FLIGHTS].value == ("demo" if mode == "demo" else "duffel_test")
    assert all(
        sources[k] == TravelDataSource.DEMO
        for k in (SearchKind.WEATHER, SearchKind.ATTRACTIONS, SearchKind.ROUTE)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("liteapi_timeout_seconds", 0),
        ("liteapi_timeout_seconds", 61),
        ("liteapi_max_retries", -1),
        ("liteapi_max_retries", 3),
        ("liteapi_max_hotels", 0),
        ("liteapi_max_hotels", 21),
        ("liteapi_max_rates_per_hotel", 0),
        ("liteapi_max_rates_per_hotel", 21),
    ],
)
def test_settings_ranges(field, value):
    with pytest.raises(ValidationError):
        settings(**{field: value})


@pytest.mark.parametrize(
    "environment,key",
    [("sandbox", "prod_unit_fake"), ("production", FAKE_KEY), ("sandbox", "unknown_unit_fake")],
)
def test_key_prefix_must_match_environment(environment, key):
    with pytest.raises(ValidationError):
        settings(liteapi_env=environment, liteapi_api_key=key)


def runtime(*, hotel_failure=False, fallback=False, barrier=None, metrics=None, hotel_limit=3):
    async def duffel(request):
        if request.url.path == "/places/suggestions":
            query = request.url.params["query"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        place(
                            query,
                            "TYO" if query == "Tokyo" else "CLE",
                            latitude=35.67,
                            longitude=139.65,
                        )
                    ]
                },
            )
        assert request.url.path == "/air/offer_requests"  # No Stays or orders.
        if barrier:
            await barrier("flights")
        return httpx.Response(200, json={"data": {"offers": [flight_offer() for _ in range(81)]}})

    async def liteapi(request):
        assert request.url.path == "/v3.0/hotels/rates"
        if barrier:
            await barrier("hotels")
        return response(status=503) if hotel_failure else response(payload(25))

    return create_travel_runtime(
        settings(liteapi_max_hotels=hotel_limit, liteapi_allow_demo_fallback=fallback),
        duffel_http=httpx.AsyncClient(
            base_url=DUFFEL_API_BASE_URL, transport=httpx.MockTransport(duffel)
        ),
        liteapi_http=httpx.AsyncClient(
            base_url=LITEAPI_BASE_URL, transport=httpx.MockTransport(liteapi)
        ),
        metrics=metrics,
    )


async def test_send_concurrency_caps_grounding_and_strict_messagepack():
    entered = set()
    both = asyncio.Event()

    async def barrier(kind):
        entered.add(kind)
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=2)

    metrics = MetricsRuntime.create()
    api = runtime(barrier=barrier, metrics=metrics)
    llm = FakeStructuredLLMProvider()
    store = InMemoryStore()
    saver = InMemorySaver(serde=create_strict_serializer())
    graph = build_travel_planning_graph(
        lambda _: [],
        search_backend=api.backend,
        checkpointer=saver,
        store=store,
        reasoning_mode="qwen",
        llm_provider=llm,
        metrics=metrics,
    )
    initial = make_state()
    initial["requirements"] = trip()
    config = {"configurable": {"thread_id": "liteapi-unit"}}
    try:
        result = await graph.ainvoke(
            initial, config=config, context=TravelRuntimeContext(user_id="unit")
        )
    finally:
        await api.aclose()
    assert entered == {"flights", "hotels"}
    assert result["error"] is None
    assert result["search_summary"]["flights"]["count"] == 5
    assert result["search_summary"]["hotels"]["count"] == 3
    assert result["search_summary"]["hotels"]["source"] == "liteapi_sandbox"
    assert all(len(prompt.flights) <= 5 and len(prompt.hotels) <= 3 for prompt in llm.plan_inputs)
    assert len(llm.review_inputs) <= 3
    snapshot = await graph.aget_state(config)
    restored = create_strict_serializer().loads_typed(
        create_strict_serializer().dumps_typed(snapshot.values)
    )
    plan = TravelPlan.model_validate(restored["travel_plan"])
    assert plan.hotel.data_source == TravelDataSource.LITEAPI_SANDBOX
    assert plan.flight.data_source == TravelDataSource.DUFFEL_TEST
    assert plan.hotel.total_stay_price is not None
    assert stable_candidate_id("flight", plan.flight) == stable_candidate_id(
        "flight", plan.flight.model_copy(update={"provider_offer_id": "changed"})
    )
    assert stable_candidate_id("hotel", plan.hotel) == stable_candidate_id(
        "hotel", plan.hotel.model_copy(update={"provider_search_result_id": "changed"})
    )
    assert await list_user_preferences(store, "unit") == []
    text = repr(restored)
    for secret in (FAKE_KEY, "X-API-Key", "Authorization", "fake-volatile", "httpx", "roomTypes"):
        assert secret not in text
    rendered = generate_latest(metrics.registry).decode()
    assert 'provider="liteapi"' in rendered
    assert 'operation="hotel_rates"' in rendered
    assert 'source="liteapi_sandbox"' in rendered
    assert FAKE_KEY not in rendered


async def test_mcp_server_domain_parity_and_fallback():
    api = runtime()

    class Context:
        lifespan_context = {"search_backend": api.backend}

    class Invoker:
        async def invoke(self, tool_name: str, request: MCPToolRequest):
            return await getattr(travel_http, tool_name)(request, Context())

    mcp = MCPTravelSearchBackend(Invoker(), sources=configured_sources(settings()))
    try:
        assert await mcp.search_hotels(trip()) == await api.backend.search_hotels(trip())
        assert await mcp.search_flights(trip()) == await api.backend.search_flights(trip())
        assert mcp.source_for(SearchKind.HOTELS) == TravelDataSource.LITEAPI_SANDBOX
    finally:
        await api.aclose()
    strict = runtime(hotel_failure=True)
    try:
        with pytest.raises(LiteAPIError):
            await strict.backend.search_hotels(trip())
    finally:
        await strict.aclose()
    fallback = runtime(hotel_failure=True, fallback=True)
    try:
        assert all(
            h.data_source == TravelDataSource.DEMO_FALLBACK
            for h in await fallback.backend.search_hotels(trip())
        )
    finally:
        await fallback.aclose()


async def test_explicit_fallback_also_obeys_candidate_cap():
    api = runtime(hotel_failure=True, fallback=True, hotel_limit=1)
    try:
        hotels = await api.backend.search_hotels(trip())
        assert len(hotels) == 1
        assert hotels[0].data_source is TravelDataSource.DEMO_FALLBACK
    finally:
        await api.aclose()


@pytest.mark.parametrize("wrong_source", [False, True])
async def test_mcp_caps_results_and_rejects_provider_crossover(wrong_source):
    api = runtime()

    class Context:
        lifespan_context = {"search_backend": api.backend}

    class Invoker:
        async def invoke(self, tool_name, request):
            result = await getattr(travel_http, tool_name)(request, Context())
            return result.model_copy(
                update={
                    "data": result.data * 20,
                    "source": TravelDataSource.DEMO if wrong_source else result.source,
                }
            )

    backend = MCPTravelSearchBackend(
        Invoker(), sources=configured_sources(settings()), hotel_limit=2
    )
    try:
        if wrong_source:
            with pytest.raises(MCPToolLayerError, match="selected provider"):
                await backend.search_hotels(trip())
        else:
            assert len(await backend.search_hotels(trip())) == 2
    finally:
        await api.aclose()


async def test_nationality_intake_and_explicit_confirmation_not_preference_memory():
    store = InMemoryStore()
    provider = FakeStructuredLLMProvider(
        intake_extractions=[
            extraction(
                origin="Cleveland",
                destination="Tokyo",
                start_date="2027-10-12",
                duration_days=5,
                travelers=1,
                budget=10000,
                currency="USD",
                guest_nationality="US",  # Deliberately hallucinated by this fake extractor.
            ),
            extraction(guest_nationality="CN"),
            extraction(guest_nationality="JP"),
        ]
    )
    intake = ConversationIntakeService(
        store=store, provider=provider, require_guest_nationality=True
    )
    state = await intake.process_message(
        user_id="unit", thread_id="intake-unit", message="A complete trip except nationality"
    )
    assert state.status == IntakeStatus.COLLECTING
    assert state.draft.guest_nationality is None
    assert state.assistant_message == "What nationality should I use for hotel pricing?"
    state = await intake.process_message(user_id="unit", thread_id="intake-unit", message="CN")
    assert state.status == IntakeStatus.AWAITING_CONFIRMATION
    state = await intake.process_message(
        user_id="unit", thread_id="intake-unit", message="国籍：JP"
    )
    _, requirements = await intake.begin_confirmation(
        user_id="unit", thread_id="intake-unit", fingerprint=state.draft_fingerprint
    )
    assert requirements.guest_nationality == "JP"
    assert state.draft.preferences == []
    assert await list_user_preferences(store, "unit") == []


def test_local_status_readiness_and_pre_stream_nationality(monkeypatch):
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock())
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock())
    with _client(settings(liteapi_api_key="")) as api:
        assert api.get("/health").status_code == 200
        assert api.get("/ready").status_code == 503
        body = api.get("/api/v1/travel-data/status").json()
        assert body["flight_provider"] == "duffel"
        assert body["hotel_provider"] == "liteapi" and body["hotel_configured"] is False
        assert body["stays_access_state"] == "not_applicable"
        assert body["environment"] is None
        assert body["flight_environment"] == "test"
        assert body["hotel_environment"] == "sandbox"
    with _client(settings()) as api:
        assert api.get("/ready").status_code == 200
        requirements = trip(guest_nationality=None).model_dump(mode="json")
        assert api.post("/api/v1/agents/plans", json=requirements).status_code == 422
        result = api.post(
            "/api/v1/agents/threads/unit/plans/stream",
            json={"user_id": "unit", "requirements": requirements},
        )
        assert result.status_code == 422
        assert "text/event-stream" not in result.headers["content-type"]


@pytest.mark.parametrize("suffix", ["", "/stream"])
@pytest.mark.parametrize("missing", ["key", "nationality"])
def test_persistent_preflight_never_invokes_graph(monkeypatch, suffix, missing):
    configuration = settings(liteapi_api_key="" if missing == "key" else FAKE_KEY)
    with _client(configuration) as api:
        graph = api.app.state.persistence.graph
        invoke = AsyncMock(side_effect=AssertionError("preflight must not run the graph"))
        monkeypatch.setattr(graph, "ainvoke", invoke)
        monkeypatch.setattr(graph, "astream", invoke)
        requirements = trip(guest_nationality=None if missing == "nationality" else "US")
        result = api.post(
            f"/api/v1/agents/threads/unit/plans{suffix}",
            json={"user_id": "unit", "requirements": requirements.model_dump(mode="json")},
        )
        assert result.status_code == (503 if missing == "key" else 422)
        assert "text/event-stream" not in result.headers["content-type"]
        invoke.assert_not_called()


def test_sse_mixed_sources_single_run_public_projection():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes

    api = runtime()
    configuration = settings()
    fakes = make_resource_fakes(configuration)
    fakes.resources.search_backend = api.backend
    fakes.resources.travel_runtime = api

    async def factory(_):
        return fakes.resources

    app = create_app(
        settings=configuration,
        resource_factory=factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(app) as web:
        result = web.post(
            "/api/v1/agents/threads/mixed-sse/plans/stream",
            json={"user_id": "unit", "requirements": trip().model_dump(mode="json")},
        )
        assert result.status_code == 200
        events, _ = parse_sse(result.text)
        assert [e["event_type"] for e in events].count("run_started") == 1
        assert [e["event_type"] for e in events].count("plan_completed") == 1
        assert events[-1]["event_type"] == "plan_completed"
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        plan = events[-1]["data"]["travel_plan"]
        assert plan["flight"]["provider_offer_id"] is None
        assert plan["hotel"]["provider_search_result_id"] is None
        assert plan["data_sources"]["hotels"] == "liteapi_sandbox"
        state = web.get("/api/v1/agents/threads/mixed-sse/state").json()
        assert (
            state["travel_plan"]["hotel"]["total_stay_price"] == plan["hotel"]["total_stay_price"]
        )
        assert FAKE_KEY not in result.text
