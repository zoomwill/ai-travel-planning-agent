"""Planner node that delegates all plan assembly to the Phase P04 service."""

from app.domain.models import TravelPlan
from app.graphs.state import TravelPlanState
from app.services import planning_service


def planner_node(state: TravelPlanState) -> TravelPlanState:
    """Create a plan when the Router selected the Planner Agent."""

    if state.get("next_agent") != "planner":
        return {
            "travel_plan": None,
            "error": state.get("error") or "The Planner Agent was not selected.",
        }

    if state.get("error") is not None:
        return {
            "travel_plan": None,
            "error": state["error"],
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

    retrieved_context = state.get("retrieved_context", [])
    if retrieved_context:
        travel_plan = _add_retrieved_context(travel_plan, retrieved_context)

    remembered_preferences = state.get("remembered_preferences", [])
    if remembered_preferences:
        travel_plan = _add_remembered_preferences(travel_plan, remembered_preferences)

    return {
        "travel_plan": travel_plan,
        "error": None,
    }


def _add_retrieved_context(
    travel_plan: TravelPlan,
    retrieved_context: list[str],
) -> TravelPlan:
    """Add retrieved knowledge to Markdown without duplicating planning rules."""

    context_lines = [f"- {context.strip()}" for context in retrieved_context if context.strip()]
    if not context_lines:
        return travel_plan
    markdown = "\n".join(
        [
            travel_plan.markdown,
            "",
            "## Retrieved travel knowledge",
            *context_lines,
        ]
    )
    return travel_plan.model_copy(update={"markdown": markdown})


def _add_remembered_preferences(
    travel_plan: TravelPlan,
    remembered_preferences: list[str],
) -> TravelPlan:
    """Show which explicit cross-thread preferences were available to the Planner."""

    preference_lines = [
        f"- {preference.strip()}" for preference in remembered_preferences if preference.strip()
    ]
    if not preference_lines:
        return travel_plan
    markdown = "\n".join(
        [
            travel_plan.markdown,
            "",
            "## Remembered preferences",
            *preference_lines,
        ]
    )
    return travel_plan.model_copy(update={"markdown": markdown})
