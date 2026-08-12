"""Shared typed state passed between deterministic LangGraph nodes."""

from typing import Annotated, Literal, TypedDict

from app.domain.models import TravelPlan, TripRequirements
from app.search.models import (
    SearchErrorEnvelope,
    SearchResultEnvelope,
    SearchSummary,
    SearchTask,
)
from app.search.reducers import (
    merge_search_results,
    merge_search_tasks,
    merge_tool_errors,
    replace_search_summary,
)


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
    search_tasks: Annotated[list[SearchTask], merge_search_tasks]
    search_results: Annotated[list[SearchResultEnvelope], merge_search_results]
    tool_errors: Annotated[list[SearchErrorEnvelope], merge_tool_errors]
    search_summary: Annotated[SearchSummary, replace_search_summary]
    travel_plan: TravelPlan | None
    error: str | None
