"""Business-specific protocol implemented by fake and Qwen providers."""

from typing import Protocol

from app.llm.models import (
    IntakePromptInput,
    PlannerPromptInput,
    QwenPlanDecision,
    QwenPlanReview,
    QwenSmokeResponse,
    QwenTripRequirementExtraction,
    ReviewerPromptInput,
    StructuredLLMResult,
)


class StructuredLLMProvider(Protocol):
    """Provide only the structured reasoning operations P14 actually needs."""

    async def plan(
        self,
        prompt_input: PlannerPromptInput,
    ) -> StructuredLLMResult[QwenPlanDecision]:
        """Select grounded travel candidates."""

    async def review(
        self,
        prompt_input: ReviewerPromptInput,
    ) -> StructuredLLMResult[QwenPlanReview]:
        """Assess a plan without controlling graph loop bounds."""

    async def extract_trip_requirements(
        self,
        prompt_input: IntakePromptInput,
    ) -> StructuredLLMResult[QwenTripRequirementExtraction]:
        """Extract one semantic patch without confirming or planning."""

    async def smoke_test(self) -> StructuredLLMResult[QwenSmokeResponse]:
        """Run the explicit minimal paid connectivity check."""

    async def aclose(self) -> None:
        """Close provider-owned network resources."""
