"""Unit tests for the explicit-memory LangGraph node."""

from datetime import date
from decimal import Decimal

import pytest
from langgraph.runtime import ExecutionInfo, Runtime
from langgraph.store.memory import InMemoryStore

from app.domain.models import Currency, TripRequirements
from app.graphs.context import TravelRuntimeContext
from app.graphs.nodes.memory_context import memory_context_node
from app.graphs.state import TravelPlanState
from app.memory.preferences import list_user_preferences


def make_state() -> TravelPlanState:
    """Include current-trip preferences that must never be saved automatically."""

    return {
        "requirements": TripRequirements(
            origin="Shanghai",
            destination="Tokyo",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            budget=Decimal("10000"),
            currency=Currency.CNY,
            travelers=1,
            preferences=["photography"],
        )
    }


def make_runtime(
    store: InMemoryStore | None,
    preferences: tuple[str, ...] = (),
) -> Runtime[TravelRuntimeContext]:
    """Build the public runtime fields that LangGraph supplies to a node."""

    return Runtime(
        context=TravelRuntimeContext(
            user_id="user-a",
            preferences_to_remember=preferences,
        ),
        store=store,
        execution_info=ExecutionInfo(
            checkpoint_id="checkpoint",
            checkpoint_ns="",
            task_id="task",
            thread_id="thread-a",
        ),
    )


@pytest.mark.asyncio
async def test_node_does_not_auto_save_requirement_preferences() -> None:
    """Only remember_preferences controls long-term writes."""

    store = InMemoryStore()
    result = await memory_context_node(make_state(), make_runtime(store))

    assert result == {"remembered_preferences": [], "error": None}
    assert await list_user_preferences(store, "user-a") == []


@pytest.mark.asyncio
async def test_node_saves_explicit_values_and_returns_all_user_memory() -> None:
    """Explicit input is upserted before the current namespace is read."""

    store = InMemoryStore()
    result = await memory_context_node(
        make_state(),
        make_runtime(store, ("Quiet neighborhoods", "Local food")),
    )

    assert result["remembered_preferences"] == ["Local food", "Quiet neighborhoods"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_node_requires_a_store_when_a_write_was_requested() -> None:
    """The graph must not pretend explicit memory was saved without a store."""

    result = await memory_context_node(
        make_state(),
        make_runtime(None, ("Quiet neighborhoods",)),
    )

    assert result == {"remembered_preferences": [], "error": "store_unavailable"}
