"""Validated JSON-safe models for deterministic travel-plan review."""

from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import QualityScore


class ReviewDecision(StrEnum):
    """The three legal outcomes of one review round."""

    ACCEPT = "accept"
    REVISE = "revise"
    FORCED_FINALIZE = "forced_finalize"


ReviewStatus: TypeAlias = Literal["pending", "accepted", "forced_finalized", "failed"]
FinalizationReason: TypeAlias = Literal[
    "threshold_reached",
    "max_review_rounds_reached",
    "critical_search_failure",
    "reviewer_failure",
    "recursion_limit_reached",
]


class ReviewIssueCode(StrEnum):
    """Stable machine-readable problems that Planner can act on."""

    MISSING_REQUIRED_CONTENT = "missing_required_content"
    BUDGET_OVERRUN = "budget_overrun"
    ITINERARY_TOO_DENSE = "itinerary_too_dense"
    PERSONALIZATION_MISSING = "personalization_missing"
    NONCRITICAL_DATA_UNAVAILABLE = "noncritical_data_unavailable"
    INCONSISTENT_DATES = "inconsistent_dates"
    INVALID_COST_BREAKDOWN = "invalid_cost_breakdown"
    GENERAL_QUALITY_ISSUE = "general_quality_issue"


class ReviewModel(BaseModel):
    """Apply strict, beginner-safe validation to every review model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class PlanReview(ReviewModel):
    """One complete structured assessment returned by a PlanReviewer."""

    review_round: int = Field(ge=1)
    draft_fingerprint: str = Field(min_length=64, max_length=64)
    scores: QualityScore
    decision: ReviewDecision
    issue_codes: list[ReviewIssueCode] = Field(default_factory=list)
    critique: str = Field(min_length=1)
    suggested_changes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_details(self) -> "PlanReview":
        """Keep accepted and revision decisions internally consistent."""

        if self.decision is not ReviewDecision.ACCEPT and not self.issue_codes:
            raise ValueError("non-accepted reviews need at least one issue code")
        if self.decision is not ReviewDecision.ACCEPT and not self.suggested_changes:
            raise ValueError("non-accepted reviews need suggested changes")
        return self


class ReviewHistoryEntry(ReviewModel):
    """A stable safe summary of one completed review round."""

    review_round: int = Field(ge=1)
    draft_fingerprint: str = Field(min_length=64, max_length=64)
    overall_score: float = Field(ge=0, le=100)
    decision: ReviewDecision
    issue_codes: list[ReviewIssueCode] = Field(default_factory=list)
    critique: str = Field(min_length=1)
    applied_feedback: list[str] = Field(default_factory=list)


class RevisionPolicy(ReviewModel):
    """Deterministic Planner controls derived from Reviewer issue codes."""

    prefer_lower_cost_options: bool = False
    max_activities_per_day: int | None = Field(default=None, ge=1)
    prioritize_preferences: bool = False
    include_missing_data_notices: bool = False

    def applied_feedback(self) -> list[str]:
        """Describe only policy changes that Planner can actually apply."""

        feedback: list[str] = []
        if self.prefer_lower_cost_options:
            feedback.append("Selected lower-cost valid flight, hotel, and activities.")
        if self.max_activities_per_day is not None:
            feedback.append(
                f"Limited optional attraction visits to {self.max_activities_per_day} per day."
            )
        if self.prioritize_preferences:
            feedback.append("Prioritized attractions using current and remembered preferences.")
        if self.include_missing_data_notices:
            feedback.append("Kept explicit notices for unavailable non-critical search data.")
        return feedback
