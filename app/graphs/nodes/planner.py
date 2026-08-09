"""Planner node that delegates all plan assembly to the Phase P04 service."""

from app.graphs.state import TravelPlanState
from app.services import planning_service


def planner_node(state: TravelPlanState) -> TravelPlanState:
    """Create a plan when the Router selected the Planner Agent."""

    if state.get("next_agent") != "planner":
        return {
            "travel_plan": None,
            "error": state.get("error") or "The Planner Agent was not selected.",
        }

    requirements = state.get("requirements")
    if requirements is None:
        return {
            "travel_plan": None,
            "error": "Validated trip requirements are required.",
        }

    try:
        travel_plan = planning_service.create_mock_travel_plan(requirements)
    except planning_service.PlanningServiceError as exc:
        return {
            "travel_plan": None,
            "error": f"Planning could not be completed during {exc.stage}.",
        }

    return {
        "travel_plan": travel_plan,
        "error": None,
    }
