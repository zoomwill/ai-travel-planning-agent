"""Create stable candidate IDs and validate every model selection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from pydantic import BaseModel

from app.domain.models import Attraction, FlightOption, HotelOption, TripRequirements
from app.llm.errors import LLMError
from app.llm.models import (
    AttractionCandidate,
    FlightCandidate,
    HotelCandidate,
    PlannerPromptInput,
    QwenPlanDecision,
    RevisionPromptSnapshot,
    TripPromptSnapshot,
)
from app.review.models import RevisionPolicy
from app.services.planning_service import GroundedPlanningSelection

CandidateKind: TypeAlias = Literal["flight", "hotel", "attraction"]
GroundingViolationReason: TypeAlias = Literal[
    "unknown_primary_candidate",
    "day_sequence",
    "duplicate_or_unknown_attraction",
    "revision_policy",
]
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bsk-(?:ws-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|redis(?:s)?|mysql|mariadb)://\S+"),
    re.compile(r"(?i)(api[_-]?key|token|password|authorization)\s*[:=]\s*\S+"),
)


class GroundingViolation(LLMError):
    """Carry one safe internal reason while preserving the public error code."""

    def __init__(
        self,
        reason: GroundingViolationReason,
        *,
        unknown_candidate_type: CandidateKind | None = None,
    ) -> None:
        self.reason = reason
        self.unknown_candidate_type = unknown_candidate_type
        super().__init__("llm_grounding_violation")


@dataclass(frozen=True, slots=True)
class GroundedPlannerInput:
    """Prompt DTO and authoritative lookup tables kept outside graph state."""

    prompt: PlannerPromptInput
    flights: dict[str, FlightOption]
    hotels: dict[str, HotelOption]
    attractions: dict[str, Attraction]


def stable_candidate_id(kind: CandidateKind, candidate: BaseModel) -> str:
    """Hash stable selection facts while excluding volatile provider metadata."""

    excluded_fields: dict[CandidateKind, set[str]] = {
        "flight": {"provider_offer_id", "expires_at", "data_source"},
        "hotel": {"provider_search_result_id", "data_source"},
        "attraction": {"data_source"},
    }
    canonical = json.dumps(
        candidate.model_dump(mode="json", exclude=excluded_fields[kind]),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{kind}_{hashlib.sha256(canonical).hexdigest()[:24]}"


def build_grounded_planner_input(
    *,
    requirements: TripRequirements,
    flights: Sequence[FlightOption],
    hotels: Sequence[HotelOption],
    attractions: Sequence[Attraction],
    retrieved_context: Sequence[str],
    remembered_preferences: Sequence[str],
    unavailable_searches: Sequence[str],
    revision_policy: RevisionPolicy,
) -> GroundedPlannerInput:
    """Build one bounded prompt and the maps used to reject hallucinated IDs."""

    flight_map = {stable_candidate_id("flight", item): item for item in flights[:20]}
    hotel_map = {stable_candidate_id("hotel", item): item for item in hotels[:20]}
    attraction_map = {stable_candidate_id("attraction", item): item for item in attractions[:40]}
    prompt = PlannerPromptInput(
        trip=_trip_snapshot(requirements, remembered_preferences),
        flights=[
            FlightCandidate(
                candidate_id=candidate_id,
                flight_number=_safe_text(item.flight_number, 80),
                airline=_safe_text(item.airline, 160),
                departure_time=item.departure_time.isoformat(),
                arrival_time=item.arrival_time.isoformat(),
                duration_minutes=item.duration_minutes,
                price=str(item.price),
                currency=item.currency.value,
            )
            for candidate_id, item in flight_map.items()
        ],
        hotels=[
            HotelCandidate(
                candidate_id=candidate_id,
                name=_safe_text(item.name, 200),
                rating=item.rating,
                price_per_night=str(item.price_per_night),
                total_stay_price=str(item.total_stay_price)
                if item.total_stay_price is not None
                else None,
                stay_nights=item.stay_nights,
                has_excluded_fees=item.has_excluded_fees,
                currency=item.currency.value,
                distance_to_center_km=item.distance_to_center_km,
                amenities=[_safe_text(value, 120) for value in item.amenities[:20]],
            )
            for candidate_id, item in hotel_map.items()
        ],
        attractions=[
            AttractionCandidate(
                candidate_id=candidate_id,
                name=_safe_text(item.name, 200),
                category=_safe_text(item.category, 100),
                description=_safe_text(item.description, 600),
                estimated_cost=str(item.estimated_cost),
                currency=item.currency.value,
                opening_hours=_safe_text(item.opening_hours, 160),
            )
            for candidate_id, item in attraction_map.items()
        ],
        retrieved_context=[_safe_text(value, 1000) for value in retrieved_context[:4]],
        unavailable_searches=[_safe_text(value, 80) for value in unavailable_searches[:5]],
        revision=RevisionPromptSnapshot.model_validate(revision_policy.model_dump()),
    )
    return GroundedPlannerInput(
        prompt=prompt,
        flights=flight_map,
        hotels=hotel_map,
        attractions=attraction_map,
    )


def validate_grounded_decision(
    decision: QwenPlanDecision,
    grounded: GroundedPlannerInput,
    *,
    requirements: TripRequirements,
    revision_policy: RevisionPolicy,
) -> GroundedPlanningSelection:
    """Resolve exact candidate IDs and reject duplicates, omissions, and policy bypass."""

    flight = grounded.flights.get(decision.selected_flight_id)
    hotel = grounded.hotels.get(decision.selected_hotel_id)
    if flight is None:
        raise GroundingViolation("unknown_primary_candidate", unknown_candidate_type="flight")
    if hotel is None:
        raise GroundingViolation("unknown_primary_candidate", unknown_candidate_type="hotel")

    day_count = (requirements.end_date - requirements.start_date).days + 1
    days = decision.daily_attraction_ids
    if [item.day_number for item in days] != list(range(1, day_count + 1)):
        raise GroundingViolation("day_sequence")

    seen: set[str] = set()
    resolved_days: list[list[Attraction]] = []
    for day in days:
        if (
            revision_policy.max_activities_per_day is not None
            and len(day.attraction_ids) > revision_policy.max_activities_per_day
        ):
            raise GroundingViolation("revision_policy")
        resolved: list[Attraction] = []
        for candidate_id in day.attraction_ids:
            attraction = grounded.attractions.get(candidate_id)
            if attraction is None:
                raise GroundingViolation(
                    "duplicate_or_unknown_attraction", unknown_candidate_type="attraction"
                )
            if candidate_id in seen:
                raise GroundingViolation("duplicate_or_unknown_attraction")
            seen.add(candidate_id)
            resolved.append(attraction)
        resolved_days.append(resolved)

    if revision_policy.prefer_lower_cost_options:
        if flight.price != min(item.price for item in grounded.flights.values()):
            raise GroundingViolation("revision_policy")
        if hotel.price_per_night != min(item.price_per_night for item in grounded.hotels.values()):
            raise GroundingViolation("revision_policy")
        selected_attractions = [item for day in resolved_days for item in day]
        if selected_attractions and grounded.attractions:
            minimum_cost = min(item.estimated_cost for item in grounded.attractions.values())
            if any(item.estimated_cost != minimum_cost for item in selected_attractions):
                raise GroundingViolation("revision_policy")

    return GroundedPlanningSelection(
        flight=flight,
        hotel=hotel,
        attractions_by_day=resolved_days,
    )


def _trip_snapshot(
    requirements: TripRequirements,
    remembered_preferences: Sequence[str],
) -> TripPromptSnapshot:
    """Create the shared bounded trip projection for Planner and Reviewer."""

    return TripPromptSnapshot(
        origin=_safe_text(requirements.origin, 120),
        destination=_safe_text(requirements.destination, 120),
        start_date=requirements.start_date.isoformat(),
        end_date=requirements.end_date.isoformat(),
        budget=str(requirements.budget),
        currency=requirements.currency.value,
        travelers=requirements.travelers,
        current_preferences=[_safe_text(value, 300) for value in requirements.preferences[:20]],
        remembered_preferences=[_safe_text(value, 300) for value in remembered_preferences[:20]],
    )


def trip_prompt_snapshot(
    requirements: TripRequirements,
    remembered_preferences: Sequence[str],
) -> TripPromptSnapshot:
    """Expose the same bounded preference projection to the Reviewer."""

    return _trip_snapshot(requirements, remembered_preferences)


def _safe_text(value: str, limit: int) -> str:
    """Bound untrusted text and redact common credential or DSN shapes."""

    normalized = " ".join(value.split())
    redacted = normalized
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    bounded = redacted[:limit].strip()
    return bounded or "[empty]"


def safe_prompt_text(value: str, limit: int) -> str:
    """Public helper for other prompt DTO builders."""

    return _safe_text(value, limit)
