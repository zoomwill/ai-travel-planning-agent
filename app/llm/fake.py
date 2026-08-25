"""Deterministic offline LLM provider for tests and local development."""

from collections.abc import Sequence

from app.llm.errors import LLMError
from app.llm.models import (
    PlannerPromptInput,
    QwenDayAttractionSelection,
    QwenPlanDecision,
    QwenPlanReview,
    QwenSmokeResponse,
    ReviewerPromptInput,
    StructuredLLMResult,
)


class FakeStructuredLLMProvider:
    """Return scripted strict models without creating any network client."""

    def __init__(
        self,
        *,
        plan_decisions: Sequence[QwenPlanDecision | LLMError] = (),
        reviews: Sequence[QwenPlanReview | LLMError] = (),
    ) -> None:
        self._plan_decisions = list(plan_decisions)
        self._reviews = list(reviews)
        self.plan_inputs: list[PlannerPromptInput] = []
        self.review_inputs: list[ReviewerPromptInput] = []
        self.close_calls = 0

    async def plan(
        self,
        prompt_input: PlannerPromptInput,
    ) -> StructuredLLMResult[QwenPlanDecision]:
        """Return a scripted decision or choose the first grounded candidates."""

        self.plan_inputs.append(prompt_input)
        if self._plan_decisions:
            decision = self._plan_decisions.pop(0)
            if isinstance(decision, LLMError):
                raise decision
        else:
            attraction_ids = [item.candidate_id for item in prompt_input.attractions]
            cursor = 0
            daily: list[QwenDayAttractionSelection] = []
            day_count = _inclusive_day_count(prompt_input)
            for day_number in range(1, day_count + 1):
                visit_count = 1 if day_number == 1 else 2
                selected = attraction_ids[cursor : cursor + visit_count]
                cursor += len(selected)
                daily.append(
                    QwenDayAttractionSelection(
                        day_number=day_number,
                        attraction_ids=selected,
                    )
                )
            decision = QwenPlanDecision(
                selected_flight_id=prompt_input.flights[0].candidate_id,
                selected_hotel_id=max(
                    prompt_input.hotels,
                    key=lambda hotel: hotel.rating,
                ).candidate_id,
                daily_attraction_ids=daily,
                planning_notes="Selected only supplied deterministic candidates.",
                preference_alignment="Applied the supplied current and remembered preferences.",
            )
        return StructuredLLMResult(value=decision, model="fake-qwen")

    async def review(
        self,
        prompt_input: ReviewerPromptInput,
    ) -> StructuredLLMResult[QwenPlanReview]:
        """Return a scripted assessment or a stable passing review."""

        self.review_inputs.append(prompt_input)
        if self._reviews:
            review = self._reviews.pop(0)
            if isinstance(review, LLMError):
                raise review
        else:
            review = QwenPlanReview(
                completeness=100,
                feasibility=100,
                personalization=100,
                budget_fit=100,
                critique="The grounded plan satisfies the bounded review criteria.",
                issue_codes=[],
                suggested_changes=[],
            )
        return StructuredLLMResult(value=review, model="fake-qwen")

    async def smoke_test(self) -> StructuredLLMResult[QwenSmokeResponse]:
        """Return a local result without pretending a real API was contacted."""

        return StructuredLLMResult(value=QwenSmokeResponse(status="ok"), model="fake-qwen")

    async def aclose(self) -> None:
        """Record cleanup so lifecycle tests can assert ownership."""

        self.close_calls += 1


def _inclusive_day_count(prompt_input: PlannerPromptInput) -> int:
    """Read the already-validated ISO dates without introducing wall-clock time."""

    from datetime import date

    start = date.fromisoformat(prompt_input.trip.start_date)
    end = date.fromisoformat(prompt_input.trip.end_date)
    return (end - start).days + 1
