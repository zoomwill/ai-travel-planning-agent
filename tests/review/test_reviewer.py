"""Unit tests for deterministic four-dimension plan scoring."""

import json
from decimal import Decimal

import pytest

from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.review.models import PlanReview, ReviewDecision, ReviewIssueCode
from app.review.reviewer import DeterministicPlanReviewer, decide_review
from tests.review.helpers import make_review_plan


async def review_plan(
    plan: TravelPlan,
    *,
    retrieved_context: list[str] | None = None,
    remembered_preferences: list[str] | None = None,
) -> PlanReview:
    """Run one default review with the documented local settings."""

    return await DeterministicPlanReviewer().review(
        draft=plan,
        requirements=plan.requirements,
        search_summary={},
        retrieved_context=retrieved_context or [],
        remembered_preferences=remembered_preferences or [],
        tool_errors=[],
        review_round=1,
        score_threshold=80,
        max_review_rounds=3,
    )


@pytest.mark.asyncio
async def test_same_review_input_is_fully_deterministic() -> None:
    """No time, random, model, or network input can change a repeated score."""

    plan = make_review_plan(preferences=["photography"])
    inputs = {
        "retrieved_context": ["Photography travelers can use a city viewpoint."],
        "remembered_preferences": ["quiet streets"],
    }

    first = await review_plan(plan, **inputs)
    second = await review_plan(plan, **inputs)

    assert first == second


@pytest.mark.asyncio
async def test_complete_neutral_plan_scores_high_and_equal_weight_mean_is_exact() -> None:
    """A complete plan with no preferences is not penalized for personalization."""

    review = await review_plan(make_review_plan())
    scores = review.scores

    assert scores.completeness == 100
    assert scores.feasibility == 100
    assert scores.personalization == 100
    assert scores.budget_fit == 100
    assert scores.overall_score == round(
        (scores.completeness + scores.feasibility + scores.personalization + scores.budget_fit) / 4,
        2,
    )
    assert review.decision is ReviewDecision.ACCEPT


@pytest.mark.asyncio
async def test_over_budget_reduces_budget_fit_with_stable_ratio() -> None:
    """Budget score is budget divided by actual total, not a subjective guess."""

    plan = make_review_plan(budget=Decimal("100.00"))
    review = await review_plan(plan)

    expected = round(float(plan.requirements.budget / plan.total_cost * Decimal(100)), 2)
    assert review.scores.budget_fit == expected
    assert ReviewIssueCode.BUDGET_OVERRUN in review.issue_codes
    assert "budget" in review.critique.casefold()


@pytest.mark.asyncio
async def test_missing_hotel_lowers_completeness() -> None:
    """Reviewer remains defensive even if an invalid test draft bypasses Pydantic validation."""

    plan = make_review_plan().model_copy(update={"hotel": None})
    review = await review_plan(plan)

    assert review.scores.completeness < 100
    assert ReviewIssueCode.MISSING_REQUIRED_CONTENT in review.issue_codes


@pytest.mark.asyncio
async def test_more_than_two_optional_visits_lowers_feasibility() -> None:
    """Arrival and weather lines are not mistaken for optional attraction visits."""

    plan = make_review_plan()
    first_day = plan.daily_itinerary[0].model_copy(
        update={
            "activities": [
                *plan.daily_itinerary[0].activities,
                "Visit Extra A",
                "Visit Extra B",
                "Visit Extra C",
            ]
        }
    )
    dense = plan.model_copy(update={"daily_itinerary": [first_day, *plan.daily_itinerary[1:]]})

    review = await review_plan(dense)

    assert review.scores.feasibility == 75
    assert ReviewIssueCode.ITINERARY_TOO_DENSE in review.issue_codes


@pytest.mark.asyncio
async def test_missing_preference_evidence_lowers_personalization() -> None:
    """A preference in requirements alone is not treated as applied planning."""

    plan = make_review_plan(preferences=["botanical gardens"])
    review = await review_plan(plan)

    assert review.scores.personalization == 0
    assert ReviewIssueCode.PERSONALIZATION_MISSING in review.issue_codes
    assert "preferences" in review.critique.casefold()


@pytest.mark.parametrize(
    ("score", "expected"),
    [(79.99, ReviewDecision.REVISE), (80.00, ReviewDecision.ACCEPT)],
)
def test_threshold_boundary_is_inclusive(score: float, expected: ReviewDecision) -> None:
    """Exactly 80 passes while 79.99 does not."""

    assert (
        decide_review(
            overall_score=score,
            score_threshold=80,
            review_round=1,
            max_review_rounds=3,
        )
        is expected
    )


@pytest.mark.asyncio
async def test_review_json_round_trips_through_strict_messagepack() -> None:
    """Checkpoint data is plain JSON and never needs pickle fallback."""

    review = await review_plan(make_review_plan())
    data = review.model_dump(mode="json")
    serializer = create_strict_serializer()

    restored = serializer.loads_typed(serializer.dumps_typed(data))

    assert PlanReview.model_validate(restored) == review


@pytest.mark.asyncio
async def test_review_output_contains_no_traceback_or_secret_fields() -> None:
    """Structured reviewer data contains only its declared safe fields."""

    review = await review_plan(make_review_plan())
    serialized = json.dumps(review.model_dump(mode="json"), sort_keys=True).casefold()

    assert "traceback" not in serialized
    assert "password" not in serialized
    assert "dsn" not in serialized
    assert "api_key" not in serialized
