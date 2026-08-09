"""Tests for deterministic Router Agent intent classification."""

import pytest

from app.graphs.nodes.router import router_node
from app.graphs.state import TravelPlanState


@pytest.mark.parametrize(
    "user_request",
    [
        "plan Tokyo trip",
        "Shanghai to Paris travel plan",
        "Please create a five-day itinerary",
    ],
)
def test_router_sends_planning_requests_to_planner(user_request: str) -> None:
    """Common travel-planning wording selects the Planner Agent."""

    state: TravelPlanState = {"user_request": user_request}

    update = router_node(state)

    assert update == {"next_agent": "planner", "error": None}


def test_router_rejects_an_empty_request() -> None:
    """An empty request produces a clear state error instead of guessing."""

    update = router_node({"user_request": "   "})

    assert update["next_agent"] is None
    assert update["error"] == "A non-empty user request is required."


def test_router_does_not_misclassify_an_unrelated_request() -> None:
    """The deterministic mock Router recognizes only its P05 planning intent."""

    update = router_node({"user_request": "Explain Python decorators"})

    assert update["next_agent"] is None
    assert update["error"] == "The request does not describe a travel plan."
