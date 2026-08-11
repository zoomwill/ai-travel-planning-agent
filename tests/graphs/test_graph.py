"""End-to-end tests for the compiled deterministic LangGraph."""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.models import Currency, TravelPlan, TripRequirements
from app.graphs.graph import build_travel_planning_graph
from app.graphs.state import TravelPlanState


def retrieve_context(query: str) -> list[str]:
    """Return fixed Paris knowledge without network access."""

    assert "Paris" in query
    return ["Montmartre offers sloping streets and broad city views."]


def make_initial_state() -> TravelPlanState:
    """Build one complete graph input state."""

    requirements = TripRequirements(
        origin="Shanghai",
        destination="Paris",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 4),
        budget=Decimal("15000.00"),
        currency=Currency.CNY,
        travelers=2,
        preferences=["museums"],
    )
    return {
        "user_request": "Shanghai to Paris travel plan",
        "requirements": requirements,
        "next_agent": None,
        "retrieved_context": [],
        "travel_plan": None,
        "error": None,
    }


@pytest.mark.asyncio
async def test_compiled_graph_runs_router_retriever_then_planner() -> None:
    """One invocation retrieves context and reaches END with a valid plan."""

    graph = build_travel_planning_graph(retrieve_context)
    final_state = await graph.ainvoke(make_initial_state())

    assert final_state["next_agent"] == "planner"
    assert final_state["error"] is None
    assert final_state["retrieved_context"] == [
        "Montmartre offers sloping streets and broad city views."
    ]
    assert isinstance(final_state["travel_plan"], TravelPlan)
    assert final_state["travel_plan"].requirements.destination == "Paris"
    assert len(final_state["travel_plan"].daily_itinerary) == 4
    assert "## Retrieved travel knowledge" in final_state["travel_plan"].markdown
    assert "Montmartre offers sloping streets" in final_state["travel_plan"].markdown


@pytest.mark.asyncio
async def test_compiled_graph_is_deterministic() -> None:
    """The same graph state produces the same final state every time."""

    graph = build_travel_planning_graph(retrieve_context)
    first = await graph.ainvoke(make_initial_state())
    second = await graph.ainvoke(make_initial_state())

    assert first == second
