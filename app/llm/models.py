"""Strict prompt and response models for bounded Qwen reasoning."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.intake.models import PartialTripRequirements, TripRequirementPatch
from app.review.models import ReviewIssueCode

LLMRole: TypeAlias = Literal["planner", "reviewer", "query_expander", "intake"]
PreferenceText: TypeAlias = Annotated[str, Field(min_length=1, max_length=300)]
AmenityText: TypeAlias = Annotated[str, Field(min_length=1, max_length=120)]
ContextText: TypeAlias = Annotated[str, Field(min_length=1, max_length=1000)]
UnavailableSearchText: TypeAlias = Annotated[str, Field(min_length=1, max_length=80)]
ActivityText: TypeAlias = Annotated[str, Field(min_length=1, max_length=300)]
SearchStatusText: TypeAlias = Annotated[str, Field(min_length=1, max_length=120)]
AttractionCandidateId: TypeAlias = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^attraction_[0-9a-f]{24}$"),
]
FlightCandidateId: TypeAlias = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^flight_[0-9a-f]{24}$"),
]
HotelCandidateId: TypeAlias = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^hotel_[0-9a-f]{24}$"),
]
SuggestedChangeText: TypeAlias = Annotated[str, Field(min_length=1, max_length=500)]


class LLMModel(BaseModel):
    """Reject unknown fields and normalize strings at every LLM boundary."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class IntakePromptInput(LLMModel):
    """Bounded incremental extraction input with no conversation history or secrets."""

    current_date: date
    current_draft: PartialTripRequirements
    user_message: str = Field(min_length=1, max_length=4000)


class QwenTripRequirementExtraction(LLMModel):
    """The only structured output Qwen may return for conversational intake."""

    patch: TripRequirementPatch


class TripPromptSnapshot(LLMModel):
    """Only trip fields needed for reasoning, with no application configuration."""

    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    budget: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)
    travelers: int = Field(ge=1, le=100)
    current_preferences: list[PreferenceText] = Field(default_factory=list, max_length=20)
    remembered_preferences: list[PreferenceText] = Field(default_factory=list, max_length=20)


class FlightCandidate(LLMModel):
    """Bounded authoritative flight candidate supplied to the model."""

    candidate_id: FlightCandidateId
    flight_number: str = Field(min_length=1, max_length=80)
    airline: str = Field(min_length=1, max_length=160)
    departure_time: str = Field(min_length=1, max_length=64)
    arrival_time: str = Field(min_length=1, max_length=64)
    duration_minutes: int = Field(gt=0)
    price: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)


class HotelCandidate(LLMModel):
    """Bounded authoritative hotel candidate supplied to the model."""

    candidate_id: HotelCandidateId
    name: str = Field(min_length=1, max_length=200)
    rating: float | None = Field(default=None, ge=0, le=5)
    price_per_night: str = Field(min_length=1, max_length=40)
    total_stay_price: str | None = Field(default=None, max_length=40)
    stay_nights: int | None = Field(default=None, ge=1, le=366)
    has_excluded_fees: bool = False
    currency: str = Field(min_length=3, max_length=3)
    distance_to_center_km: float | None = Field(default=None, ge=0)
    amenities: list[AmenityText] = Field(default_factory=list, max_length=20)


class AttractionCandidate(LLMModel):
    """Bounded authoritative attraction candidate supplied to the model."""

    candidate_id: AttractionCandidateId
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=600)
    estimated_cost: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)
    opening_hours: str = Field(min_length=1, max_length=160)


class RevisionPromptSnapshot(LLMModel):
    """Allowlisted application actions that a revised choice must satisfy."""

    prefer_lower_cost_options: bool = False
    max_activities_per_day: int | None = Field(default=None, ge=1, le=8)
    prioritize_preferences: bool = False
    include_missing_data_notices: bool = False


class PlannerPromptInput(LLMModel):
    """Complete bounded input for candidate selection, never full graph state."""

    trip: TripPromptSnapshot
    flights: list[FlightCandidate] = Field(min_length=1, max_length=20)
    hotels: list[HotelCandidate] = Field(min_length=1, max_length=20)
    attractions: list[AttractionCandidate] = Field(default_factory=list, max_length=40)
    retrieved_context: list[ContextText] = Field(default_factory=list, max_length=4)
    unavailable_searches: list[UnavailableSearchText] = Field(default_factory=list, max_length=5)
    revision: RevisionPromptSnapshot
    grounding_repair: bool = False


class QwenDayAttractionSelection(LLMModel):
    """Grounded attraction IDs selected for one requested calendar day."""

    day_number: int = Field(strict=True, ge=1, le=366)
    attraction_ids: list[AttractionCandidateId] = Field(default_factory=list, max_length=8)


class QwenPlanDecision(LLMModel):
    """Qwen choices only; prices and provider facts are intentionally absent."""

    selected_flight_id: FlightCandidateId
    selected_hotel_id: HotelCandidateId
    daily_attraction_ids: list[QwenDayAttractionSelection] = Field(
        min_length=1,
        max_length=366,
    )
    planning_notes: str = Field(min_length=1, max_length=1000)
    preference_alignment: str = Field(min_length=1, max_length=1000)


class ReviewDaySnapshot(LLMModel):
    """One bounded itinerary day used for semantic quality assessment."""

    day_number: int = Field(ge=1, le=366)
    date: str = Field(min_length=10, max_length=10)
    activities: list[ActivityText] = Field(min_length=1, max_length=12)
    estimated_cost: str = Field(min_length=1, max_length=40)


class ReviewPlanSnapshot(LLMModel):
    """Safe plan projection that omits Markdown and unrelated internal state."""

    flight_number: str = Field(min_length=1, max_length=80)
    airline: str = Field(min_length=1, max_length=160)
    flight_price: str = Field(min_length=1, max_length=40)
    hotel_name: str = Field(min_length=1, max_length=200)
    hotel_price_per_night: str = Field(min_length=1, max_length=40)
    hotel_total_stay_price: str | None = Field(default=None, max_length=40)
    hotel_has_excluded_fees: bool = False
    days: list[ReviewDaySnapshot] = Field(min_length=1, max_length=366)
    total_cost: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)
    budget_warning_present: bool


class ReviewerPromptInput(LLMModel):
    """Complete bounded input for one semantic review round."""

    trip: TripPromptSnapshot
    plan: ReviewPlanSnapshot
    search_statuses: list[SearchStatusText] = Field(default_factory=list, max_length=5)
    retrieved_context: list[ContextText] = Field(default_factory=list, max_length=4)
    retrieval_available: bool
    review_round: int = Field(ge=1)


class QwenPlanReview(LLMModel):
    """Semantic dimensions and allowlisted issues; no loop decision field."""

    completeness: float = Field(strict=True, ge=0, le=100)
    feasibility: float = Field(strict=True, ge=0, le=100)
    personalization: float = Field(strict=True, ge=0, le=100)
    budget_fit: float = Field(strict=True, ge=0, le=100)
    critique: str = Field(min_length=1, max_length=2000)
    issue_codes: list[ReviewIssueCode] = Field(default_factory=list, max_length=8)
    suggested_changes: list[SuggestedChangeText] = Field(default_factory=list, max_length=8)


class QwenSmokeResponse(LLMModel):
    """Tiny response used only by the explicit paid smoke command."""

    status: Literal["ok"]


OutputT = TypeVar("OutputT", bound=LLMModel)


@dataclass(frozen=True, slots=True)
class StructuredLLMResult(Generic[OutputT]):
    """Validated model value plus real provider usage when supplied."""

    value: OutputT
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
