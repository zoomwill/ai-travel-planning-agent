"""Reviewer node and bounded conditional routing for the P09 reflection loop."""

from typing import Literal

from pydantic import ValidationError

from app.domain.models import TravelPlan
from app.graphs.state import TravelPlanState
from app.review.fingerprint import create_draft_fingerprint
from app.review.models import (
    FinalizationReason,
    PlanReview,
    ReviewDecision,
    ReviewHistoryEntry,
)
from app.review.reviewer import PlanReviewer, decide_review
from app.review.revision import policy_for_issues
from app.search.models import dump_model_json


async def reviewer_node(
    state: TravelPlanState,
    *,
    reviewer: PlanReviewer,
    score_threshold: float,
    max_review_rounds: int,
) -> TravelPlanState:
    """Review one draft and write only validated JSON-safe review data."""

    draft_data = state.get("draft_plan")
    if draft_data is None:
        return _review_failure("review_output_invalid")

    review_round = state.get("review_round", 0) + 1
    try:
        draft = TravelPlan.model_validate(draft_data)
        raw_review = await reviewer.review(
            draft=draft,
            requirements=draft.requirements,
            search_summary=state.get("search_summary", {}),
            retrieved_context=state.get("retrieved_context", []),
            remembered_preferences=state.get("remembered_preferences", []),
            tool_errors=state.get("tool_errors", []),
            review_round=review_round,
            score_threshold=score_threshold,
            max_review_rounds=max_review_rounds,
        )
        review = PlanReview.model_validate(raw_review)
    except ValidationError:
        return _review_failure("review_output_invalid")
    except Exception:
        return _review_failure("reviewer_failed")

    expected_fingerprint = create_draft_fingerprint(draft)
    if review.review_round != review_round or review.draft_fingerprint != expected_fingerprint:
        return _review_failure("review_output_invalid")

    decision = decide_review(
        overall_score=review.scores.overall_score,
        score_threshold=score_threshold,
        review_round=review_round,
        max_review_rounds=max_review_rounds,
    )
    review_data = review.model_dump(mode="json")
    review_data["decision"] = decision
    try:
        review = PlanReview.model_validate(review_data)
    except ValidationError:
        return _review_failure("review_output_invalid")
    policy = policy_for_issues(review.issue_codes)
    history_entry = ReviewHistoryEntry(
        review_round=review.review_round,
        draft_fingerprint=review.draft_fingerprint,
        overall_score=review.scores.overall_score,
        decision=review.decision,
        issue_codes=review.issue_codes,
        critique=review.critique,
        applied_feedback=state.get("applied_feedback", []),
    )

    review_status: Literal["pending", "accepted", "forced_finalized"] = "pending"
    finalization_reason: FinalizationReason | None = None
    if decision is ReviewDecision.ACCEPT:
        review_status = "accepted"
        finalization_reason = "threshold_reached"
    elif decision is ReviewDecision.FORCED_FINALIZE:
        review_status = "forced_finalized"
        finalization_reason = "max_review_rounds_reached"

    return {
        "current_review": dump_model_json(review),
        "review_history": [dump_model_json(history_entry)],
        "review_round": review_round,
        "critique": review.critique,
        "revision_policy": dump_model_json(policy),
        "review_status": review_status,
        "finalization_reason": finalization_reason,
        "error": None,
    }


def route_after_review(state: TravelPlanState) -> Literal["planner", "finalize_plan"]:
    """Return Planner only for a valid revise decision; every other path terminates."""

    if state.get("review_status") == "pending":
        review_data = state.get("current_review")
        if review_data is not None:
            try:
                if PlanReview.model_validate(review_data).decision is ReviewDecision.REVISE:
                    return "planner"
            except ValidationError:
                pass
    return "finalize_plan"


def _review_failure(error_code: str) -> TravelPlanState:
    """Return a safe failure without exception text, traceback, or reviewer repr."""

    return {
        "current_review": None,
        "critique": "The deterministic quality review could not complete.",
        "revision_policy": None,
        "review_status": "failed",
        "finalization_reason": "reviewer_failure",
        "error": error_code,
    }
