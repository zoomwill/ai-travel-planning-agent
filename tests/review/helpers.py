"""Deterministic review doubles and plan factories used only by tests."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.models import Currency, QualityScore, TravelPlan, TripRequirements
from app.review.fingerprint import create_draft_fingerprint
from app.review.models import PlanReview, ReviewIssueCode
from app.review.reviewer import decide_review
from app.search.models import SearchErrorEnvelope, SearchSummary
from app.services.planning_service import create_mock_travel_plan


def make_review_requirements(
    *,
    budget: Decimal = Decimal("10000.00"),
    preferences: list[str] | None = None,
) -> TripRequirements:
    """Create one stable Tokyo request for reviewer tests."""

    return TripRequirements(
        origin="Shanghai",
        destination="Tokyo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        budget=budget,
        currency=Currency.CNY,
        travelers=1,
        preferences=preferences or [],
    )


def make_review_plan(
    *,
    budget: Decimal = Decimal("10000.00"),
    preferences: list[str] | None = None,
) -> TravelPlan:
    """Create one complete plan through the unchanged P04 entry point."""

    return create_mock_travel_plan(make_review_requirements(budget=budget, preferences=preferences))


@dataclass(frozen=True, slots=True)
class ScriptedReviewStep:
    """One fixed set of dimension scores and issue codes for a test review round."""

    completeness: float
    feasibility: float
    personalization: float
    budget_fit: float
    issue_codes: tuple[ReviewIssueCode, ...] = ()

    @property
    def overall_score(self) -> float:
        """Use the same documented equal-weight formula as production."""

        return round(
            (self.completeness + self.feasibility + self.personalization + self.budget_fit) / 4,
            2,
        )


class ScriptedPlanReviewer:
    """Return fixed test scores while still binding each review to the actual draft."""

    def __init__(self, steps: Sequence[ScriptedReviewStep]) -> None:
        if not steps:
            raise ValueError("at least one scripted review step is required")
        self.steps = tuple(steps)
        self.calls = 0
        self.drafts: list[TravelPlan] = []

    async def review(
        self,
        *,
        draft: TravelPlan,
        requirements: TripRequirements,
        search_summary: SearchSummary,
        retrieved_context: Sequence[str],
        retrieval_error: str | None = None,
        remembered_preferences: Sequence[str],
        tool_errors: Sequence[SearchErrorEnvelope],
        review_round: int,
        score_threshold: float,
        max_review_rounds: int,
    ) -> PlanReview:
        """Return the next script entry without consulting time, random, or network."""

        del (
            requirements,
            search_summary,
            retrieved_context,
            retrieval_error,
            remembered_preferences,
            tool_errors,
        )
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        self.drafts.append(draft)
        critique = (
            "Scripted quality review passed."
            if not step.issue_codes
            else "Scripted deterministic revision guidance."
        )
        scores = QualityScore(
            completeness=step.completeness,
            feasibility=step.feasibility,
            personalization=step.personalization,
            budget_fit=step.budget_fit,
            overall_score=step.overall_score,
            critique=critique,
        )
        return PlanReview(
            review_round=review_round,
            draft_fingerprint=create_draft_fingerprint(draft),
            scores=scores,
            decision=decide_review(
                overall_score=step.overall_score,
                score_threshold=score_threshold,
                review_round=review_round,
                max_review_rounds=max_review_rounds,
            ),
            issue_codes=list(step.issue_codes),
            critique=critique,
            suggested_changes=(
                ["Apply the scripted deterministic revision policy."] if step.issue_codes else []
            ),
        )


class FailingPlanReviewer:
    """Raise a private test error so graph sanitization can be asserted."""

    def __init__(self) -> None:
        self.calls = 0

    async def review(self, **kwargs: object) -> PlanReview:
        """Fail once without allowing the private detail into graph State."""

        del kwargs
        self.calls += 1
        raise RuntimeError("private reviewer traceback secret")
