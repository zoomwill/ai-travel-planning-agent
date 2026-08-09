"""End-to-end tests for the compiled deterministic LangGraph."""

from datetime import date
from decimal import Decimal

from app.domain.models import Currency, TravelPlan, TripRequirements
from app.graphs.graph import travel_planning_graph
from app.graphs.state import TravelPlanState


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
        "travel_plan": None,
        "error": None,
    }


def test_compiled_graph_runs_router_then_planner() -> None:
    """One invocation reaches END with a validated travel plan."""

    final_state = travel_planning_graph.invoke(make_initial_state())

    assert final_state["next_agent"] == "planner"
    assert final_state["error"] is None
    assert isinstance(final_state["travel_plan"], TravelPlan)
    assert final_state["travel_plan"].requirements.destination == "Paris"
    assert len(final_state["travel_plan"].daily_itinerary) == 4


def test_compiled_graph_is_deterministic() -> None:
    """The same graph state produces the same final state every time."""

    first = travel_planning_graph.invoke(make_initial_state())
    second = travel_planning_graph.invoke(make_initial_state())

    assert first == second
