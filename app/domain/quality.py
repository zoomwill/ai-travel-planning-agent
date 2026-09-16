"""Bounded public projections, not a second review execution state machine."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewIssueCode(StrEnum):
    """Application-owned issue vocabulary shared with Reviewer and the UI."""

    MISSING_REQUIRED_CONTENT = "missing_required_content"
    BUDGET_OVERRUN = "budget_overrun"
    ITINERARY_TOO_DENSE = "itinerary_too_dense"
    PERSONALIZATION_MISSING = "personalization_missing"
    NONCRITICAL_DATA_UNAVAILABLE = "noncritical_data_unavailable"
    INCONSISTENT_DATES = "inconsistent_dates"
    INVALID_COST_BREAKDOWN = "invalid_cost_breakdown"
    GENERAL_QUALITY_ISSUE = "general_quality_issue"


class PlanWarning(StrEnum):
    """Safe codes; neither vendor text nor model-generated explanations."""

    ROUTE_UNAVAILABLE = "route_unavailable"
    HISTORICAL_ROUTE_UNVERIFIED = "historical_route_unverified"
    ATTRACTIONS_UNAVAILABLE = "attractions_unavailable"
    WEATHER_UNAVAILABLE = "weather_unavailable"
    RETURN_FLIGHT_EXCLUDED = "return_flight_excluded"
    EXCLUDED_HOTEL_FEES = "excluded_hotel_fees"


class PlanQuality(BaseModel):
    """Read-only summary of the existing terminal review fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    review_status: Literal["accepted", "forced_finalized", "unavailable"] = "unavailable"
    review_rounds: int = Field(default=0, ge=0)
    final_score: float | None = Field(default=None, ge=0, le=100)
    finalization_reason: Literal["threshold_reached", "max_review_rounds_reached"] | None = None
    issue_codes: list[ReviewIssueCode] = Field(default_factory=list, max_length=8)
