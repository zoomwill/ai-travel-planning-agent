"""Shared typed state passed between deterministic LangGraph nodes."""

from typing import Literal, TypedDict

from app.domain.models import TravelPlan, TripRequirements


class TravelPlanState(TypedDict, total=False):
    """Values read or updated while the deterministic agent graph runs.

    ``total=False`` lets each node return only the fields it changes. The API
    still creates all five fields explicitly so the initial state is easy for
    a beginner to inspect.
    """

    user_request: str
    requirements: TripRequirements
    next_agent: Literal["planner"] | None
    remembered_preferences: list[str]
    retrieved_context: list[str]
    travel_plan: TravelPlan | None
    error: str | None
