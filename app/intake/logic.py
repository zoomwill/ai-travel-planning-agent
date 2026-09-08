"""Deterministic merge, date, validation, summary, and fingerprint logic."""

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import cast

from pydantic import ValidationError

from app.domain.models import TripRequirements
from app.intake.models import (
    PartialTripRequirements,
    RequirementField,
    TripRequirementPatch,
    complete_trip_requirements,
)
from app.memory.preferences import clean_preference_value, normalize_preference

_REQUIRED_FIELD_ORDER = tuple(
    RequirementField(field_name)
    for field_name, model_field in TripRequirements.model_fields.items()
    if model_field.is_required()
)

_QUESTION_TEMPLATES: dict[RequirementField, str] = {
    RequirementField.ORIGIN: "What city will you travel from?",
    RequirementField.DESTINATION: "What is your destination?",
    RequirementField.START_DATE: "What exact date would you like to depart?",
    RequirementField.END_DATE: "What is the last trip date or trip duration you would like?",
    RequirementField.DURATION_DAYS: "How many inclusive calendar days should the trip last?",
    RequirementField.TRAVELERS: "How many people are traveling?",
    RequirementField.BUDGET: "What is the total trip budget?",
    RequirementField.CURRENCY: "Which currency should the budget use?",
    RequirementField.PREFERENCES: "Which preferences should be kept for this trip?",
    RequirementField.GUEST_NATIONALITY: "What nationality should I use for hotel pricing?",
}


def require_explicit_nationality(message: str, patch: TripRequirementPatch) -> TripRequirementPatch:
    """Accept a nationality code only from an unambiguous current-message answer.

    A bare code or a dedicated nationality field is accepted. Other natural-language messages
    require a separate clarification; a model cannot borrow the origin, locale or old context.
    """

    code = patch.guest_nationality
    if code is None:
        return patch
    answer = message.strip().rstrip(".!。！")
    explicit = (
        answer.upper() == code
        or re.fullmatch(
            rf"(?:my\s+|我的)?(?:guest[_ -]?nationality|nationality|国籍)"
            rf"\s*(?:is\s+|[:：=为是]\s*)?[\"']?{re.escape(code)}[\"']?",
            answer,
            flags=re.IGNORECASE,
        )
        is not None
    )
    if explicit:
        return patch
    return TripRequirementPatch.model_validate(
        patch.model_dump(exclude_unset=True, exclude={"guest_nationality"})
    )


def merge_requirement_patch(
    draft: PartialTripRequirements,
    patch: TripRequirementPatch,
) -> PartialTripRequirements:
    """Apply one patch without clearing any field that the patch did not mention."""

    values = draft.model_dump()
    for field in patch.clear_fields:
        if field == RequirementField.PREFERENCES:
            values["preferences"] = []
        else:
            values[field.value] = None

    scalar_fields = (
        "origin",
        "destination",
        "start_date",
        "end_date",
        "duration_days",
        "budget",
        "currency",
        "travelers",
        "guest_nationality",
    )
    for field_name in scalar_fields:
        if field_name in patch.model_fields_set:
            value = getattr(patch, field_name)
            values[field_name] = Decimal(str(value)) if field_name == "budget" else value

    preferences = _merge_preferences(
        values.get("preferences", []),
        additions=patch.preferences_add,
        removals=patch.preferences_remove,
    )
    values["preferences"] = preferences
    _derive_dates(values, patch)
    return PartialTripRequirements.model_validate(values)


def _merge_preferences(
    current: object,
    *,
    additions: list[str],
    removals: list[str],
) -> list[str]:
    """Remove and add preferences through the same normalized comparison form."""

    current_values = current if isinstance(current, list) else []
    removed = {normalize_preference(value) for value in removals}
    unique: dict[str, str] = {}
    for value in [*current_values, *additions]:
        if not isinstance(value, str):
            continue
        cleaned = clean_preference_value(value)
        normalized = normalize_preference(cleaned)
        if normalized and normalized not in removed:
            unique.setdefault(normalized, cleaned)
    return list(unique.values())


def _derive_dates(values: dict[str, object], patch: TripRequirementPatch) -> None:
    """Derive inclusive dates in application code rather than trusting model arithmetic."""

    start_value = values.get("start_date")
    end_value = values.get("end_date")
    start = cast(date | None, start_value)
    end = cast(date | None, end_value)
    duration = values.get("duration_days")
    start_changed = "start_date" in patch.model_fields_set
    end_changed = "end_date" in patch.model_fields_set
    duration_changed = "duration_days" in patch.model_fields_set
    cleared = set(patch.clear_fields)
    start_cleared = RequirementField.START_DATE in cleared
    end_cleared = RequirementField.END_DATE in cleared
    duration_cleared = RequirementField.DURATION_DAYS in cleared

    if (
        start_changed
        and not end_changed
        and not end_cleared
        and start is not None
        and isinstance(duration, int)
    ):
        values["end_date"] = start + timedelta(days=duration - 1)
        return
    if (
        end_changed
        and not start_changed
        and not start_cleared
        and end is not None
        and isinstance(duration, int)
    ):
        values["start_date"] = end - timedelta(days=duration - 1)
        return
    if duration_changed and not end_cleared and start is not None and isinstance(duration, int):
        values["end_date"] = start + timedelta(days=duration - 1)
        return
    if start is not None and end is not None and not duration_changed and not duration_cleared:
        day_count = (end - start).days + 1
        values["duration_days"] = day_count if 1 <= day_count <= 366 else None
        return
    if start is not None and end is None and not end_cleared and isinstance(duration, int):
        values["end_date"] = start + timedelta(days=duration - 1)
    elif end is not None and start is None and not start_cleared and isinstance(duration, int):
        values["start_date"] = end - timedelta(days=duration - 1)


def missing_requirement_fields(
    draft: PartialTripRequirements,
    *,
    require_guest_nationality: bool = False,
) -> list[RequirementField]:
    """Compute required fields from the real TripRequirements model, never from Qwen."""

    required = (
        (*_REQUIRED_FIELD_ORDER, RequirementField.GUEST_NATIONALITY)
        if require_guest_nationality
        else _REQUIRED_FIELD_ORDER
    )
    return [field for field in required if getattr(draft, field.value) is None]


def invalid_requirement_fields(draft: PartialTripRequirements) -> list[RequirementField]:
    """Return deterministic cross-field failures that a partial model must preserve."""

    invalid: list[RequirementField] = []
    if draft.start_date is not None and draft.end_date is not None:
        day_count = (draft.end_date - draft.start_date).days + 1
        if day_count < 1:
            invalid.append(RequirementField.END_DATE)
        elif day_count > 366:
            invalid.append(RequirementField.END_DATE)
        if draft.duration_days is not None and draft.duration_days != day_count:
            invalid.append(RequirementField.DURATION_DAYS)

    if not missing_requirement_fields(draft) and not invalid:
        try:
            complete_trip_requirements(draft)
        except ValidationError as exc:
            for error in exc.errors():
                if error["loc"]:
                    field_name = str(error["loc"][0])
                    try:
                        field = RequirementField(field_name)
                    except ValueError:
                        continue
                    if field not in invalid:
                        invalid.append(field)
    return invalid


def draft_fingerprint(draft: PartialTripRequirements) -> str:
    """Hash canonical effective draft JSON so stale confirmation cannot use Python hash()."""

    if not missing_requirement_fields(draft) and not invalid_requirement_fields(draft):
        value = complete_trip_requirements(draft).model_dump(mode="json")
    else:
        value = draft.model_dump(mode="json", exclude_none=True)
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assistant_message_for(
    draft: PartialTripRequirements,
    missing_fields: list[RequirementField],
    invalid_fields: list[RequirementField],
) -> str:
    """Ask at most two fixed-priority questions or request explicit confirmation."""

    needs_attention = [*invalid_fields, *missing_fields]
    ordered = list(dict.fromkeys(needs_attention))[:2]
    if ordered:
        return " ".join(_QUESTION_TEMPLATES[field] for field in ordered)

    requirements = complete_trip_requirements(draft)
    preferences = ", ".join(requirements.preferences) or "none"
    return (
        "I have everything needed: "
        f"{requirements.origin} to {requirements.destination}, "
        f"{requirements.start_date.isoformat()} through {requirements.end_date.isoformat()}, "
        f"{requirements.travelers} traveler(s), budget {requirements.budget} "
        f"{requirements.currency.value}, preferences: {preferences}. "
        + (
            f"Hotel pricing nationality: {requirements.guest_nationality}. "
            if requirements.guest_nationality is not None
            else ""
        )
        + "Please confirm this exact draft before planning."
    )
