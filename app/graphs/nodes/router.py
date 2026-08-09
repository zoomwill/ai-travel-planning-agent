"""Deterministic intent routing for the Phase P05 graph."""

from typing import Final

from app.graphs.state import TravelPlanState

_PLANNING_KEYWORDS: Final[tuple[str, ...]] = (
    "plan",
    "trip",
    "travel",
    "itinerary",
    "行程",
    "旅行",
    "旅游",
)


def router_node(state: TravelPlanState) -> TravelPlanState:
    """Route a travel-planning request to the only P05 downstream node."""

    user_request = state.get("user_request", "").strip().casefold()
    if not user_request:
        return {
            "next_agent": None,
            "error": "A non-empty user request is required.",
        }

    if any(keyword in user_request for keyword in _PLANNING_KEYWORDS):
        return {
            "next_agent": "planner",
            "error": None,
        }

    return {
        "next_agent": None,
        "error": "The request does not describe a travel plan.",
    }
