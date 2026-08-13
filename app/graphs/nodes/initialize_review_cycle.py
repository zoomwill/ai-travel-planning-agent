"""Reset P09 review state before Planner creates a new request's first draft."""

from typing import Any

from langgraph.types import Overwrite

from app.graphs.state import TravelPlanState


def initialize_review_cycle_node(state: TravelPlanState) -> dict[str, Any]:
    """Clear only review/final-plan fields without touching search, RAG, or memory."""

    return {
        "draft_plan": _reset_value(state, "draft_plan", None),
        "current_review": _reset_value(state, "current_review", None),
        "review_history": _reset_value(state, "review_history", []),
        "review_round": _reset_value(state, "review_round", 0),
        "critique": _reset_value(state, "critique", None),
        "revision_policy": _reset_value(state, "revision_policy", None),
        "applied_feedback": _reset_value(state, "applied_feedback", []),
        "review_status": _reset_value(state, "review_status", "pending"),
        "finalization_reason": _reset_value(state, "finalization_reason", None),
        "travel_plan": _reset_value(state, "travel_plan", None),
        "error": state.get("error"),
    }


def _reset_value(state: TravelPlanState, field: str, value: Any) -> Any:
    """Use Overwrite for existing thread state and a raw first value for absent channels."""

    if field in state:
        return Overwrite(value=value)
    return value
