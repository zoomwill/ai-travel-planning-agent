"""End-to-end offline tests for P08 LangGraph fan-out, fan-in, and reset."""

import asyncio
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.core.persistence import create_strict_serializer
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.search.models import SearchKind, create_request_fingerprint
from tests.graphs.test_persistence import config, make_state
from tests.search.helpers import BarrierSearchBackend, RecordingSearchBackend


@pytest.mark.asyncio
async def test_send_fan_out_enters_all_five_workers_before_release() -> None:
    """A shared barrier fails under sequential execution and passes under real fan-out."""

    backend = BarrierSearchBackend()
    graph = build_travel_planning_graph(lambda query: [], search_backend=backend)
    run = asyncio.create_task(
        graph.ainvoke(
            make_state(),
            context=TravelRuntimeContext(user_id="barrier-user"),
        )
    )

    try:
        await asyncio.wait_for(backend.all_started.wait(), timeout=2)
        assert backend.started == set(SearchKind)
    finally:
        backend.release.set()
    result = await asyncio.wait_for(run, timeout=2)

    assert result["travel_plan"] is not None
    assert all(count == 1 for count in backend.calls.values())


@pytest.mark.asyncio
async def test_planner_does_not_repeat_any_provider_search() -> None:
    """Five workers call five backend methods once and Planner performs no second query."""

    backend = RecordingSearchBackend()
    graph = build_travel_planning_graph(lambda query: [], search_backend=backend)

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="count-user"),
    )

    assert result["travel_plan"] is not None
    assert backend.calls == {kind: 1 for kind in SearchKind}


@pytest.mark.asyncio
async def test_noncritical_weather_failure_returns_degraded_plan() -> None:
    """Weather failure preserves four successes and never invents a forecast."""

    backend = RecordingSearchBackend(fail_kind=SearchKind.WEATHER)
    graph = build_travel_planning_graph(
        lambda query: ["Retrieved Paris knowledge"],
        search_backend=backend,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="degraded-user"),
    )

    assert result["error"] is None
    assert len(result["search_results"]) == 4
    assert len(result["tool_errors"]) == 1
    assert result["search_summary"]["weather"] == {
        "status": "error",
        "count": 0,
        "source": "demo",
    }
    assert "Weather information unavailable." in result["travel_plan"].markdown
    assert "this plan does not invent it" in result["travel_plan"].markdown
    assert "Retrieved Paris knowledge" in result["travel_plan"].markdown


@pytest.mark.asyncio
async def test_critical_flight_failure_keeps_other_results_without_plan() -> None:
    """Missing flights is a safe critical error while sibling results remain inspectable."""

    graph = build_travel_planning_graph(
        lambda query: [],
        search_backend=RecordingSearchBackend(fail_kind=SearchKind.FLIGHTS),
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="critical-user"),
    )

    assert result["travel_plan"] is None
    assert result["error"] == "critical_search_failed:flights"
    assert len(result["search_results"]) == 4
    assert result["tool_errors"][0]["kind"] == "flights"


@pytest.mark.asyncio
async def test_same_thread_second_request_overwrites_old_search_state() -> None:
    """Paris tasks and results replace Tokyo data on a durable thread."""

    saver = InMemorySaver(serde=create_strict_serializer())
    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=saver,
        store=InMemoryStore(),
    )
    thread_config = config("reset-thread")
    tokyo_state = make_state()
    tokyo_state["requirements"] = tokyo_state["requirements"].model_copy(
        update={"destination": "Tokyo"}
    )
    tokyo_state["user_request"] = "Shanghai to Tokyo travel plan"
    await graph.ainvoke(
        tokyo_state,
        config=thread_config,
        context=TravelRuntimeContext(user_id="reset-user"),
    )

    paris_state = make_state()
    result = await graph.ainvoke(
        paris_state,
        config=thread_config,
        context=TravelRuntimeContext(user_id="reset-user"),
    )
    snapshot = await graph.aget_state(thread_config)

    expected_fingerprint = create_request_fingerprint(paris_state["requirements"])
    assert len(result["search_tasks"]) == 5
    assert len(result["search_results"]) == 5
    assert {task["request_fingerprint"] for task in result["search_tasks"]} == {
        expected_fingerprint
    }
    assert "Tokyo" not in json.dumps(result["search_results"])
    assert snapshot.values["requirements"].destination == "Paris"


@pytest.mark.asyncio
async def test_threads_remain_isolated_and_strict_state_round_trips() -> None:
    """P08 JSON data persists beside typed P07 state without crossing threads."""

    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    tokyo = make_state()
    tokyo["requirements"] = tokyo["requirements"].model_copy(update={"destination": "Tokyo"})
    tokyo["user_request"] = "Shanghai to Tokyo travel plan"
    await graph.ainvoke(
        tokyo,
        config=config("tokyo-thread"),
        context=TravelRuntimeContext(user_id="user-a"),
    )
    await graph.ainvoke(
        make_state(),
        config=config("paris-thread"),
        context=TravelRuntimeContext(user_id="user-a"),
    )

    tokyo_snapshot = await graph.aget_state(config("tokyo-thread"))
    paris_snapshot = await graph.aget_state(config("paris-thread"))

    assert tokyo_snapshot.values["requirements"].destination == "Tokyo"
    assert paris_snapshot.values["requirements"].destination == "Paris"
    assert len(tokyo_snapshot.values["search_results"]) == 5
    assert len(paris_snapshot.values["search_results"]) == 5
    json.dumps(paris_snapshot.values["search_results"])
