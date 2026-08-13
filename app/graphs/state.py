"""Shared typed state passed between deterministic LangGraph nodes."""

from typing import Annotated, Literal, TypedDict

from app.domain.models import TravelPlan, TripRequirements
from app.graphs.reducers import replace_state_value
from app.review.history import merge_review_history
from app.review.models import FinalizationReason, ReviewStatus
from app.search.models import (
    JsonObject,
    JsonValue,  # noqa: F401 - needed when LangGraph resolves recursive JsonObject hints
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
    draft_plan: Annotated[JsonObject | None, replace_state_value]
    current_review: Annotated[JsonObject | None, replace_state_value]
    review_history: Annotated[list[JsonObject], merge_review_history]
    review_round: Annotated[int, replace_state_value]
    critique: Annotated[str | None, replace_state_value]
    revision_policy: Annotated[JsonObject | None, replace_state_value]
    applied_feedback: Annotated[list[str], replace_state_value]
    review_status: Annotated[ReviewStatus, replace_state_value]
    finalization_reason: Annotated[FinalizationReason | None, replace_state_value]
    travel_plan: Annotated[TravelPlan | None, replace_state_value]
    error: str | None
