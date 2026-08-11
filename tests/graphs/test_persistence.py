"""Offline graph tests for checkpoints, history, and cross-thread memory."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.core.persistence import create_strict_serializer
from app.domain.models import Currency, TravelPlan, TripRequirements
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.graphs.state import TravelPlanState
from app.memory.preferences import list_user_preferences


class FailingSearchStore(InMemoryStore):
    """Raise during memory reads so graph error propagation can be tested."""

    async def asearch(self, *args: Any, **kwargs: Any) -> list[Any]:
        """Simulate an unavailable preference store."""

        del args, kwargs
        raise RuntimeError("private store detail")


def make_state(preferences: list[str] | None = None) -> TravelPlanState:
    """Build one typed state containing current-trip preferences."""

    requirements = TripRequirements(
        origin="Shanghai",
        destination="Paris",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
        budget=Decimal("15000"),
        currency=Currency.CNY,
        travelers=2,
        preferences=preferences or ["museums"],
    )
    return {
        "user_request": "Shanghai to Paris travel plan",
        "requirements": requirements,
        "next_agent": None,
        "remembered_preferences": [],
        "retrieved_context": [],
        "travel_plan": None,
        "error": None,
    }


def config(thread_id: str) -> RunnableConfig:
    """Return the exact configurable key required by a checkpointer."""

    return {"configurable": {"thread_id": thread_id}}


@pytest.mark.asyncio
async def test_checkpoint_round_trip_preserves_current_typed_state() -> None:
    """Strict MessagePack restores Pydantic models, Decimal values, and dates."""

    graph = build_travel_planning_graph(
        lambda query: ["Paris context"],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    await graph.ainvoke(
        make_state(),
        config=config("typed-thread"),
        context=TravelRuntimeContext(user_id="user-a"),
    )

    snapshot = await graph.aget_state(config("typed-thread"))
    assert isinstance(snapshot.values["requirements"], TripRequirements)
    assert isinstance(snapshot.values["travel_plan"], TravelPlan)
    assert snapshot.values["requirements"].budget == Decimal("15000")
    assert snapshot.values["requirements"].start_date == date(2026, 10, 1)


@pytest.mark.asyncio
async def test_history_contains_multiple_node_checkpoints_and_respects_limit() -> None:
    """One graph run can be inspected newest-first with a caller limit."""

    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    await graph.ainvoke(
        make_state(),
        config=config("history-thread"),
        context=TravelRuntimeContext(user_id="user-a"),
    )

    all_snapshots = [
        snapshot async for snapshot in graph.aget_state_history(config("history-thread"))
    ]
    limited = [
        snapshot async for snapshot in graph.aget_state_history(config("history-thread"), limit=2)
    ]
    assert len(all_snapshots) >= 6
    assert len(limited) == 2
    assert all_snapshots[0].created_at >= all_snapshots[-1].created_at


@pytest.mark.asyncio
async def test_same_user_recalls_across_threads_and_other_user_is_isolated() -> None:
    """Store namespaces cross thread boundaries but never cross user boundaries."""

    store = InMemoryStore()
    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=store,
    )
    first = await graph.ainvoke(
        make_state(),
        config=config("thread-one"),
        context=TravelRuntimeContext(
            user_id="user-a",
            preferences_to_remember=("Quiet neighborhoods",),
        ),
    )
    second = await graph.ainvoke(
        make_state(),
        config=config("thread-two"),
        context=TravelRuntimeContext(user_id="user-a"),
    )
    isolated = await graph.ainvoke(
        make_state(),
        config=config("thread-three"),
        context=TravelRuntimeContext(user_id="user-b"),
    )

    assert first["remembered_preferences"] == ["Quiet neighborhoods"]
    assert second["remembered_preferences"] == ["Quiet neighborhoods"]
    assert "## Remembered preferences" in second["travel_plan"].markdown
    assert isolated["remembered_preferences"] == []


@pytest.mark.asyncio
async def test_requirement_preferences_influence_retrieval_but_are_not_stored() -> None:
    """Current request context is usable without silently becoming long-term memory."""

    queries: list[str] = []
    store = InMemoryStore()
    graph = build_travel_planning_graph(
        lambda query: queries.append(query) or [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=store,
    )
    await graph.ainvoke(
        make_state(["photography"]),
        config=config("no-auto-memory"),
        context=TravelRuntimeContext(user_id="user-a"),
    )

    assert "Current trip preferences: photography" in queries[0]
    assert await list_user_preferences(store, "user-a") == []


@pytest.mark.asyncio
async def test_store_failure_stops_the_graph_and_preserves_safe_error() -> None:
    """Router and Planner must not erase an upstream memory failure."""

    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=FailingSearchStore(),
    )
    result = await graph.ainvoke(
        make_state(),
        config=config("store-failure-thread"),
        context=TravelRuntimeContext(user_id="user-a"),
    )

    assert result["error"] == "store_unavailable"
    assert result["next_agent"] is None
    assert result["travel_plan"] is None
