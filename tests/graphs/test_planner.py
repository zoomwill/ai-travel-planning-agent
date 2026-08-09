"""Tests for the Planner Agent node."""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.models import Currency, TripRequirements
from app.graphs.nodes.planner import planner_node
from app.graphs.state import TravelPlanState
from app.services import planning_service


def make_requirements() -> TripRequirements:
    """Build validated requirements without any external service calls."""

    return TripRequirements(
        origin="Shanghai",
        destination="Tokyo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        budget=Decimal("10000.00"),
        currency=Currency.CNY,
        travelers=1,
        preferences=[],
    )


def test_planner_reuses_existing_planning_service() -> None:
    """The node returns the same deterministic plan as the P04 service."""

    requirements = make_requirements()
    state: TravelPlanState = {
        "user_request": "plan Tokyo trip",
        "requirements": requirements,
        "next_agent": "planner",
        "travel_plan": None,
        "error": None,
    }

    update = planner_node(state)

    assert update["travel_plan"] == planning_service.create_mock_travel_plan(requirements)
    assert update["error"] is None


def test_planner_does_not_run_when_router_selected_nothing() -> None:
    """A Router error passes through the fixed graph without planning."""

    update = planner_node(
        {
            "next_agent": None,
            "error": "The request does not describe a travel plan.",
        }
    )

    assert update["travel_plan"] is None
    assert update["error"] == "The request does not describe a travel plan."


def test_planner_reports_service_failure_without_private_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The graph state carries a safe stage instead of a provider traceback."""

    def fail(requirements: TripRequirements) -> None:
        del requirements
        try:
            raise RuntimeError("private provider detail")
        except RuntimeError as exc:
            raise planning_service.PlanningServiceError("flight search") from exc

    monkeypatch.setattr(planning_service, "create_mock_travel_plan", fail)

    update = planner_node(
        {
            "requirements": make_requirements(),
            "next_agent": "planner",
        }
    )

    assert update["travel_plan"] is None
    assert update["error"] == "Planning could not be completed during flight search."
    assert "private provider detail" not in update["error"]
