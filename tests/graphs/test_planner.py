"""Tests for the P08 Planner that combines completed search data."""

from datetime import date
from decimal import Decimal
from typing import NoReturn

import pytest

from app.domain.models import Currency, TravelPlan, TripRequirements
from app.graphs.nodes.aggregate_search_results import aggregate_search_results_node
from app.graphs.nodes.planner import planner_node
from app.graphs.state import TravelPlanState
from app.search.models import SearchKind, SearchResultEnvelope, create_search_tasks, dump_model_json
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


def make_completed_search_state() -> TravelPlanState:
    """Create the JSON-safe worker output expected at the Planner boundary."""

    requirements = make_requirements()
    tasks = {task["kind"]: task for task in create_search_tasks(requirements)}
    providers = planning_service.MOCK_PLANNING_PROVIDERS
    data_by_kind = {
        SearchKind.FLIGHTS.value: [
            dump_model_json(item) for item in providers.search_flights(requirements)
        ],
        SearchKind.HOTELS.value: [
            dump_model_json(item) for item in providers.search_hotels(requirements)
        ],
        SearchKind.ATTRACTIONS.value: [
            dump_model_json(item) for item in providers.search_attractions(requirements)
        ],
        SearchKind.WEATHER.value: [
            dump_model_json(item) for item in providers.get_weather(requirements)
        ],
        SearchKind.ROUTE.value: [
            dump_model_json(providers.get_route(requirements.origin, requirements.destination))
        ],
    }
    search_results = [
        SearchResultEnvelope(
            task_id=tasks[kind]["task_id"],
            kind=kind,
            status="ok",
            data=data,
        )
        for kind, data in data_by_kind.items()
    ]
    state: TravelPlanState = {
        "user_request": "plan Tokyo trip",
        "requirements": requirements,
        "next_agent": "planner",
        "retrieved_context": [],
        "remembered_preferences": [],
        "search_tasks": list(tasks.values()),
        "search_results": search_results,
        "tool_errors": [],
        "travel_plan": None,
        "error": None,
    }
    state.update(aggregate_search_results_node(state))
    return state


def test_planner_reuses_p04_assembly_rules_without_repeating_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node matches P04 output and never calls its provider-running entry point."""

    state = make_completed_search_state()
    requirements = state["requirements"]
    expected = planning_service.create_mock_travel_plan(requirements)

    def repeated_provider_call(_: TripRequirements) -> NoReturn:
        raise AssertionError("Planner repeated provider searches")

    monkeypatch.setattr(
        planning_service,
        "create_mock_travel_plan",
        repeated_provider_call,
    )

    update = planner_node(state)

    assert update["travel_plan"] is None
    assert TravelPlan.model_validate(update["draft_plan"]) == expected
    assert update["error"] is None


def test_planner_does_not_run_when_router_selected_nothing() -> None:
    """A Router error passes through the graph without planning."""

    update = planner_node(
        {
            "next_agent": None,
            "error": "The request does not describe a travel plan.",
        }
    )

    assert update["travel_plan"] is None
    assert update["error"] == "The request does not describe a travel plan."


def test_planner_reports_assembly_failure_without_private_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The graph state carries a stable code instead of an assembly traceback."""

    def fail(**_: object) -> NoReturn:
        try:
            raise RuntimeError("private provider detail")
        except RuntimeError as exc:
            raise planning_service.PlanningServiceError("plan assembly") from exc

    monkeypatch.setattr(planning_service, "assemble_travel_plan_from_results", fail)

    update = planner_node(make_completed_search_state())

    assert update["travel_plan"] is None
    assert update["error"] == "plan_assembly_failed"
    assert "private provider detail" not in update["error"]
