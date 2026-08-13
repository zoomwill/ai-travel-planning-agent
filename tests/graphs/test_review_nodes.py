"""Focused tests for P09 initialize, reviewer, routing, and finalize nodes."""

import pytest
from langgraph.types import Overwrite

from app.domain.models import TravelPlan
from app.graphs.nodes.finalize_plan import finalize_plan_node
from app.graphs.nodes.initialize_review_cycle import initialize_review_cycle_node
from app.graphs.nodes.reviewer import reviewer_node, route_after_review
from app.graphs.state import TravelPlanState
from app.review.models import ReviewIssueCode
from app.search.models import dump_model_json
from tests.review.helpers import (
    ScriptedPlanReviewer,
    ScriptedReviewStep,
    make_review_plan,
)


def old_review_state() -> TravelPlanState:
    """Build state resembling a completed older request on a reused thread."""

    plan = make_review_plan()
    return {
        "draft_plan": dump_model_json(plan),
        "current_review": {"old": True},
        "review_history": [{"old": True}],
        "review_round": 3,
        "critique": "old critique",
        "revision_policy": {"old": True},
        "applied_feedback": ["old feedback"],
        "review_status": "accepted",
        "finalization_reason": "threshold_reached",
        "travel_plan": plan,
        "error": None,
    }


def test_initialize_review_cycle_uses_overwrite_for_every_old_review_field() -> None:
    """A reused thread receives reducer-bypassing reset values and keeps no old plan."""

    update = initialize_review_cycle_node(old_review_state())

    expected = {
        "draft_plan": None,
        "current_review": None,
        "review_history": [],
        "review_round": 0,
        "critique": None,
        "revision_policy": None,
        "applied_feedback": [],
        "review_status": "pending",
        "finalization_reason": None,
        "travel_plan": None,
    }
    for field, value in expected.items():
        assert isinstance(update[field], Overwrite)
        assert update[field].value == value


def test_initialize_review_cycle_supports_missing_first_run_channels() -> None:
    """A total=False minimal first input receives raw defaults rather than wrapper values."""

    update = initialize_review_cycle_node({"error": None})

    assert update["review_round"] == 0
    assert update["draft_plan"] is None
    assert not isinstance(update["review_round"], Overwrite)


@pytest.mark.asyncio
async def test_reviewer_node_writes_json_review_history_and_revision_policy() -> None:
    """Machine issue codes become a safe policy but never edit the draft in Reviewer."""

    plan = make_review_plan(preferences=["museums"])
    state: TravelPlanState = {
        "draft_plan": dump_model_json(plan),
        "review_round": 0,
        "applied_feedback": [],
        "search_summary": {},
        "retrieved_context": [],
        "remembered_preferences": [],
        "tool_errors": [],
    }
    reviewer = ScriptedPlanReviewer(
        [
            ScriptedReviewStep(
                100,
                100,
                0,
                100,
                (ReviewIssueCode.PERSONALIZATION_MISSING,),
            )
        ]
    )

    update = await reviewer_node(
        state,
        reviewer=reviewer,
        score_threshold=80,
        max_review_rounds=3,
    )

    assert "draft_plan" not in update
    assert update["review_round"] == 1
    assert update["revision_policy"]["prioritize_preferences"] is True
    assert len(update["review_history"]) == 1
    assert route_after_review(update) == "planner"


def test_finalize_marks_forced_plan_without_claiming_threshold_passed() -> None:
    """Maximum-round output contains the required honest explanation."""

    plan = make_review_plan()
    result = finalize_plan_node(
        {
            "draft_plan": dump_model_json(plan),
            "review_status": "forced_finalized",
            "finalization_reason": "max_review_rounds_reached",
            "error": None,
        }
    )

    final_plan = TravelPlan.model_validate(result["travel_plan"])
    assert "maximum review rounds were reached" in final_plan.markdown
    assert "passed the configured" not in final_plan.markdown


@pytest.mark.asyncio
async def test_wrong_reviewer_fingerprint_becomes_safe_invalid_output() -> None:
    """Reviewer cannot attach a valid-looking score to a different draft."""

    class WrongFingerprintReviewer(ScriptedPlanReviewer):
        async def review(self, **kwargs: object):
            review = await super().review(**kwargs)
            return review.model_copy(update={"draft_fingerprint": "f" * 64})

    plan = make_review_plan()
    reviewer = WrongFingerprintReviewer([ScriptedReviewStep(100, 100, 100, 100)])
    update = await reviewer_node(
        {
            "draft_plan": dump_model_json(plan),
            "review_round": 0,
            "search_summary": {},
            "retrieved_context": [],
            "remembered_preferences": [],
            "tool_errors": [],
        },
        reviewer=reviewer,
        score_threshold=80,
        max_review_rounds=3,
    )

    assert update["error"] == "review_output_invalid"
    assert update["review_status"] == "failed"
    assert update["finalization_reason"] == "reviewer_failure"
    assert route_after_review(update) == "finalize_plan"


@pytest.mark.asyncio
async def test_recomputed_revision_decision_is_validated_again() -> None:
    """A low score cannot become a revision without issues and suggested changes."""

    reviewer = ScriptedPlanReviewer([ScriptedReviewStep(100, 100, 100, 100)])
    original_review = await reviewer.review(
        draft=make_review_plan(),
        requirements=make_review_plan().requirements,
        search_summary={},
        retrieved_context=[],
        remembered_preferences=[],
        tool_errors=[],
        review_round=1,
        score_threshold=80,
        max_review_rounds=3,
    )

    class ContradictoryReviewer(ScriptedPlanReviewer):
        async def review(self, **kwargs: object):
            return original_review.model_copy(
                update={"scores": original_review.scores.model_copy(update={"overall_score": 0})}
            )

    plan = make_review_plan()
    update = await reviewer_node(
        {
            "draft_plan": dump_model_json(plan),
            "review_round": 0,
            "search_summary": {},
            "retrieved_context": [],
            "remembered_preferences": [],
            "tool_errors": [],
        },
        reviewer=ContradictoryReviewer([ScriptedReviewStep(100, 100, 100, 100)]),
        score_threshold=80,
        max_review_rounds=3,
    )

    assert update["error"] == "review_output_invalid"
    assert route_after_review(update) == "finalize_plan"


def test_finalize_without_draft_returns_safe_failure() -> None:
    """Finalize never invents a TravelPlan when no validated draft exists."""

    result = finalize_plan_node({"draft_plan": None})

    assert result["travel_plan"] is None
    assert result["review_status"] == "failed"
    assert result["error"] == "finalization_failed"
