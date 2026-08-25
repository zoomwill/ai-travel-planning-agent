"""Qwen-backed reviewer that preserves deterministic P09 loop control."""

from collections.abc import Sequence

from app.domain.models import QualityScore, TravelPlan, TripRequirements
from app.llm.diagnostics import record_deterministic_fallback
from app.llm.errors import LLMError
from app.llm.grounding import safe_prompt_text, trip_prompt_snapshot
from app.llm.models import (
    ReviewDaySnapshot,
    ReviewerPromptInput,
    ReviewPlanSnapshot,
)
from app.llm.protocol import StructuredLLMProvider
from app.observability.metrics import MetricsRuntime
from app.review.fingerprint import create_draft_fingerprint
from app.review.models import PlanReview, ReviewDecision, ReviewIssueCode
from app.review.reviewer import PlanReviewer, decide_review
from app.search.models import SearchErrorEnvelope, SearchSummary

_DEFAULT_CHANGE = "Apply the allowlisted structured review issue."


class FallbackPlanReviewer:
    """Use deterministic review only when the operator explicitly enabled fallback."""

    def __init__(
        self,
        primary: "QwenPlanReviewer",
        fallback: PlanReviewer,
        metrics: MetricsRuntime | None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._metrics = metrics

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
        """Catch one stable LLM failure and delegate once to the local reviewer."""

        try:
            return await self._primary.review(
                draft=draft,
                requirements=requirements,
                search_summary=search_summary,
                retrieved_context=retrieved_context,
                retrieval_error=retrieval_error,
                remembered_preferences=remembered_preferences,
                tool_errors=tool_errors,
                review_round=review_round,
                score_threshold=score_threshold,
                max_review_rounds=max_review_rounds,
            )
        except LLMError as exc:
            record_deterministic_fallback(self._metrics, "reviewer", exc.code)
            return await self._fallback.review(
                draft=draft,
                requirements=requirements,
                search_summary=search_summary,
                retrieved_context=retrieved_context,
                retrieval_error=retrieval_error,
                remembered_preferences=remembered_preferences,
                tool_errors=tool_errors,
                review_round=review_round,
                score_threshold=score_threshold,
                max_review_rounds=max_review_rounds,
            )


class QwenPlanReviewer:
    """Use Qwen dimensions and critique while the application owns loop safety."""

    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider

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
        """Convert one strict Qwen assessment into the existing PlanReview model."""

        prompt_input = ReviewerPromptInput(
            trip=trip_prompt_snapshot(requirements, remembered_preferences),
            plan=ReviewPlanSnapshot(
                flight_number=safe_prompt_text(draft.flight.flight_number, 80),
                airline=safe_prompt_text(draft.flight.airline, 160),
                flight_price=str(draft.flight.price),
                hotel_name=safe_prompt_text(draft.hotel.name, 200),
                hotel_price_per_night=str(draft.hotel.price_per_night),
                days=[
                    ReviewDaySnapshot(
                        day_number=day.day_number,
                        date=day.date.isoformat(),
                        activities=[safe_prompt_text(value, 300) for value in day.activities[:12]],
                        estimated_cost=str(day.estimated_cost),
                    )
                    for day in draft.daily_itinerary
                ],
                total_cost=str(draft.total_cost),
                currency=draft.currency.value,
                budget_warning_present=draft.budget_warning is not None,
            ),
            search_statuses=[
                f"{kind}:{summary['status']}" for kind, summary in sorted(search_summary.items())
            ][:5],
            retrieved_context=[safe_prompt_text(value, 1000) for value in retrieved_context[:4]],
            retrieval_available=retrieval_error is None,
            review_round=review_round,
        )
        result = await self._provider.review(prompt_input)
        assessment = result.value
        overall_score = round(
            (
                assessment.completeness
                + assessment.feasibility
                + assessment.personalization
                + assessment.budget_fit
            )
            / 4,
            2,
        )
        decision = decide_review(
            overall_score=overall_score,
            score_threshold=score_threshold,
            review_round=review_round,
            max_review_rounds=max_review_rounds,
        )
        issue_codes = list(dict.fromkeys(assessment.issue_codes))
        suggested_changes = list(assessment.suggested_changes)
        if decision is not ReviewDecision.ACCEPT and not issue_codes:
            issue_codes = [ReviewIssueCode.GENERAL_QUALITY_ISSUE]
        if decision is not ReviewDecision.ACCEPT and not suggested_changes:
            suggested_changes = [_DEFAULT_CHANGE]
        critique = assessment.critique
        scores = QualityScore(
            completeness=assessment.completeness,
            feasibility=assessment.feasibility,
            personalization=assessment.personalization,
            budget_fit=assessment.budget_fit,
            overall_score=overall_score,
            critique=critique,
        )
        return PlanReview(
            review_round=review_round,
            draft_fingerprint=create_draft_fingerprint(draft),
            scores=scores,
            decision=decision,
            issue_codes=issue_codes,
            critique=critique,
            suggested_changes=suggested_changes,
        )
