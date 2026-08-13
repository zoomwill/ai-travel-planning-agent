"""Offline end-to-end tests for the bounded P09 reflection loop."""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.store.memory import InMemoryStore

from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.review.models import PlanReview, ReviewDecision, ReviewIssueCode
from app.search.models import SearchKind
from tests.graphs.test_persistence import config, make_state
from tests.review.helpers import (
    FailingPlanReviewer,
    ScriptedPlanReviewer,
    ScriptedReviewStep,
)
from tests.search.helpers import RecordingSearchBackend

PASS_STEP = ScriptedReviewStep(100, 100, 100, 100)
PERSONALIZATION_REVISION_STEP = ScriptedReviewStep(
    100,
    100,
    0,
    100,
    (ReviewIssueCode.PERSONALIZATION_MISSING,),
)
BUDGET_REVISION_STEP = ScriptedReviewStep(
    100,
    100,
    100,
    0,
    (ReviewIssueCode.BUDGET_OVERRUN,),
)


def first_visit(plan: TravelPlan) -> str:
    """Read the first actual attraction activity from one structured draft."""

    return next(
        activity
        for day in plan.daily_itinerary
        for activity in day.activities
        if activity.startswith("Visit ")
    )


@pytest.mark.asyncio
async def test_default_reviewer_accepts_complete_plan_on_first_round() -> None:
    """Normal deterministic data reaches Finalize without an unnecessary loop."""

    graph = build_travel_planning_graph(lambda query: ["Paris museum context"])

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="normal-user"),
    )

    review = PlanReview.model_validate(result["current_review"])
    assert isinstance(result["travel_plan"], TravelPlan)
    assert result["review_round"] == 1
    assert result["review_status"] == "accepted"
    assert result["finalization_reason"] == "threshold_reached"
    assert review.decision is ReviewDecision.ACCEPT
    assert review.scores.overall_score >= 80


@pytest.mark.asyncio
async def test_scripted_first_failure_revises_real_draft_then_passes() -> None:
    """Critique changes attraction ordering and fingerprint before second acceptance."""

    backend = RecordingSearchBackend()
    reviewer = ScriptedPlanReviewer([PERSONALIZATION_REVISION_STEP, PASS_STEP])
    retrieval_queries: list[str] = []
    graph = build_travel_planning_graph(
        lambda query: retrieval_queries.append(query) or ["Paris museum context"],
        search_backend=backend,
        plan_reviewer=reviewer,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="revision-user"),
    )

    assert reviewer.calls == 2
    assert len(reviewer.drafts) == 2
    assert first_visit(reviewer.drafts[0]) != first_visit(reviewer.drafts[1])
    assert "City Museum" in first_visit(reviewer.drafts[1])
    assert len({entry["draft_fingerprint"] for entry in result["review_history"]}) == 2
    assert result["review_history"][1]["applied_feedback"]
    assert result["review_round"] == 2
    assert result["review_status"] == "accepted"
    assert result["finalization_reason"] == "threshold_reached"
    assert backend.calls == {kind: 1 for kind in SearchKind}
    assert len(retrieval_queries) == 1


@pytest.mark.asyncio
async def test_always_low_score_stops_at_exact_max_rounds_and_forces_finalize() -> None:
    """Default max three means three Reviewer calls, never a fourth."""

    reviewer = ScriptedPlanReviewer([BUDGET_REVISION_STEP])
    graph = build_travel_planning_graph(
        lambda query: [],
        plan_reviewer=reviewer,
        review_max_rounds=3,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="forced-user"),
    )

    assert reviewer.calls == 3
    assert result["review_round"] == 3
    assert len(result["review_history"]) == 3
    assert result["review_status"] == "forced_finalized"
    assert result["finalization_reason"] == "max_review_rounds_reached"
    final_review = PlanReview.model_validate(result["current_review"])
    assert final_review.decision is ReviewDecision.FORCED_FINALIZE
    assert "maximum review rounds were reached" in result["travel_plan"].markdown


@pytest.mark.asyncio
async def test_reviewer_exception_runs_once_and_preserves_only_safe_failure() -> None:
    """Reviewer faults do not retry forever or copy private exception text into State."""

    reviewer = FailingPlanReviewer()
    graph = build_travel_planning_graph(lambda query: [], plan_reviewer=reviewer)

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="failure-user"),
    )

    serialized = json.dumps(result, default=str).casefold()
    assert reviewer.calls == 1
    assert result["error"] == "reviewer_failed"
    assert result["review_status"] == "failed"
    assert result["finalization_reason"] == "reviewer_failure"
    assert isinstance(result["travel_plan"], TravelPlan)
    assert "private reviewer traceback secret" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_critical_search_failure_skips_reviewer() -> None:
    """A missing flight keeps P08's safe failure and never reviews a None draft."""

    reviewer = ScriptedPlanReviewer([PASS_STEP])
    graph = build_travel_planning_graph(
        lambda query: [],
        search_backend=RecordingSearchBackend(fail_kind=SearchKind.FLIGHTS),
        plan_reviewer=reviewer,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="critical-user"),
    )

    assert reviewer.calls == 0
    assert result["draft_plan"] is None
    assert result["travel_plan"] is None
    assert result["error"] == "critical_search_failed:flights"
    assert result["finalization_reason"] == "critical_search_failure"


@pytest.mark.asyncio
async def test_noncritical_degraded_plan_is_still_reviewed() -> None:
    """A disclosed weather failure retains four results and reaches quality review."""

    reviewer = ScriptedPlanReviewer([PASS_STEP])
    graph = build_travel_planning_graph(
        lambda query: [],
        search_backend=RecordingSearchBackend(fail_kind=SearchKind.WEATHER),
        plan_reviewer=reviewer,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="degraded-user"),
    )

    assert reviewer.calls == 1
    assert len(result["search_results"]) == 4
    assert result["tool_errors"][0]["kind"] == "weather"
    assert "Weather information unavailable." in result["travel_plan"].markdown


@pytest.mark.asyncio
async def test_same_thread_new_request_overwrites_old_review_cycle() -> None:
    """Paris starts again at round one and contains no Tokyo review fingerprint."""

    reviewer = ScriptedPlanReviewer([PASS_STEP])
    graph = build_travel_planning_graph(
        lambda query: [],
        plan_reviewer=reviewer,
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    thread_config = config("review-reset-thread")
    tokyo = make_state()
    tokyo["requirements"] = tokyo["requirements"].model_copy(update={"destination": "Tokyo"})
    tokyo["user_request"] = "Shanghai to Tokyo travel plan"
    first = await graph.ainvoke(
        tokyo,
        config=thread_config,
        context=TravelRuntimeContext(user_id="reset-user"),
    )
    first_fingerprint = first["review_history"][0]["draft_fingerprint"]

    second = await graph.ainvoke(
        make_state(),
        config=thread_config,
        context=TravelRuntimeContext(user_id="reset-user"),
    )

    assert second["requirements"].destination == "Paris"
    assert second["review_round"] == 1
    assert len(second["review_history"]) == 1
    assert second["review_history"][0]["draft_fingerprint"] != first_fingerprint
    assert first_fingerprint not in json.dumps(second["review_history"])


@pytest.mark.asyncio
async def test_strict_checkpoint_round_trip_keeps_json_review_state() -> None:
    """P09 review data survives strict MessagePack without duplicate entries."""

    graph = build_travel_planning_graph(
        lambda query: [],
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    thread_config = config("strict-review-thread")
    await graph.ainvoke(
        make_state(),
        config=thread_config,
        context=TravelRuntimeContext(user_id="strict-user"),
    )

    snapshot = await graph.aget_state(thread_config)

    assert isinstance(snapshot.values["travel_plan"], TravelPlan)
    assert isinstance(snapshot.values["draft_plan"], dict)
    assert isinstance(snapshot.values["current_review"], dict)
    assert len(snapshot.values["review_history"]) == snapshot.values["review_round"]
    json.dumps(snapshot.values["review_history"])


@pytest.mark.asyncio
async def test_low_recursion_limit_raises_official_safety_error() -> None:
    """LangGraph provides a second safety layer beyond max review rounds."""

    graph = build_travel_planning_graph(lambda query: [])

    with pytest.raises(GraphRecursionError):
        await graph.ainvoke(
            make_state(),
            config={"recursion_limit": 1},
            context=TravelRuntimeContext(user_id="recursion-user"),
        )


def test_compiled_graph_mermaid_contains_review_loop_and_finalize_branch() -> None:
    """The inspectable graph matches the documented bounded reflection topology."""

    mermaid = build_travel_planning_graph(lambda query: []).get_graph().draw_mermaid()

    assert "reviewer" in mermaid
    assert "planner" in mermaid
    assert "finalize_plan" in mermaid
    assert "reviewer -.-> planner" in mermaid
    assert "reviewer -.-> finalize_plan" in mermaid
