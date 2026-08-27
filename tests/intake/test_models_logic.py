"""Pure P15 draft, patch, date, validation, and fingerprint tests."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import Currency
from app.intake.logic import (
    draft_fingerprint,
    invalid_requirement_fields,
    merge_requirement_patch,
    missing_requirement_fields,
)
from app.intake.models import (
    PartialTripRequirements,
    RequirementField,
    TripRequirementPatch,
    complete_trip_requirements,
)


def complete_draft(**updates: object) -> PartialTripRequirements:
    """Build one valid inclusive three-day intake draft."""

    values: dict[str, object] = {
        "origin": "Cleveland",
        "destination": "Tokyo",
        "start_date": date(2026, 10, 12),
        "end_date": date(2026, 10, 14),
        "duration_days": 3,
        "budget": Decimal("3000.00"),
        "currency": Currency.USD,
        "travelers": 1,
        "preferences": ["photography"],
    }
    values.update(updates)
    return PartialTripRequirements.model_validate(values)


def test_empty_and_valid_partial_drafts_are_json_safe() -> None:
    empty = PartialTripRequirements()
    draft = complete_draft()

    assert empty.model_dump(exclude_none=True) == {"preferences": []}
    assert draft.budget == Decimal("3000.00")
    assert draft.currency is Currency.USD
    assert draft.model_dump(mode="json")["start_date"] == "2026-10-12"


def test_partial_model_validates_numbers_duration_and_preferences() -> None:
    draft = PartialTripRequirements(
        budget=Decimal("1.25"),
        travelers=2,
        duration_days=366,
        preferences=[" Photography ", "photography", "Quiet neighborhoods"],
    )

    assert draft.preferences == ["Photography", "Quiet neighborhoods"]
    for values in (
        {"budget": Decimal("-1")},
        {"travelers": 0},
        {"duration_days": 0},
        {"duration_days": 367},
        {"travelers": "2"},
    ):
        with pytest.raises(ValidationError):
            PartialTripRequirements.model_validate(values)


def test_patch_preserves_old_values_and_supports_corrections() -> None:
    first = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(
            destination="Tokyo",
            budget=3000,
            preferences_add=["museums", "Photography"],
        ),
    )
    corrected = merge_requirement_patch(
        first,
        TripRequirementPatch(
            destination="Paris",
            budget=2500.5,
            preferences_add=["photography"],
            preferences_remove=["MUSEUMS"],
        ),
    )

    assert corrected.destination == "Paris"
    assert corrected.budget == Decimal("2500.5")
    assert corrected.preferences == ["Photography"]
    assert corrected.origin is None


def test_patch_clear_is_explicit_and_no_unmentioned_field_is_cleared() -> None:
    draft = complete_draft()
    unchanged = merge_requirement_patch(draft, TripRequirementPatch(destination="Paris"))
    cleared = merge_requirement_patch(
        unchanged,
        TripRequirementPatch(clear_fields=[RequirementField.START_DATE]),
    )

    assert unchanged.origin == "Cleveland"
    assert unchanged.start_date == date(2026, 10, 12)
    assert cleared.start_date is None
    assert RequirementField.START_DATE in missing_requirement_fields(cleared)
    assert cleared.end_date == date(2026, 10, 14)


def test_patch_rejects_null_numeric_strings_and_conflicting_operations() -> None:
    with pytest.raises(ValidationError):
        TripRequirementPatch.model_validate({"budget": "2500"})
    with pytest.raises(ValidationError):
        TripRequirementPatch.model_validate({"budget": 2500.123})
    with pytest.raises(ValidationError):
        TripRequirementPatch.model_validate({"travelers": "2"})
    with pytest.raises(ValidationError):
        TripRequirementPatch.model_validate({"destination": None})
    with pytest.raises(ValidationError):
        TripRequirementPatch(
            destination="Paris",
            clear_fields=[RequirementField.DESTINATION],
        )
    with pytest.raises(ValidationError):
        TripRequirementPatch(
            preferences_add=["museums"],
            preferences_remove=["Museums"],
        )


@pytest.mark.parametrize(
    "missing",
    [
        RequirementField.ORIGIN,
        RequirementField.DESTINATION,
        RequirementField.START_DATE,
        RequirementField.END_DATE,
        RequirementField.BUDGET,
        RequirementField.TRAVELERS,
    ],
)
def test_missing_fields_come_from_real_domain_requirements(missing: RequirementField) -> None:
    draft = complete_draft(**{missing.value: None})

    assert missing in missing_requirement_fields(draft)
    assert RequirementField.CURRENCY not in missing_requirement_fields(
        complete_draft(currency=None)
    )


def test_date_derivation_uses_inclusive_semantics_in_both_directions() -> None:
    from_start = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(start_date=date(2026, 10, 12), duration_days=5),
    )
    from_end = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(end_date=date(2026, 10, 16), duration_days=5),
    )
    one_day = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(start_date=date(2026, 10, 12), duration_days=1),
    )

    assert from_start.end_date == date(2026, 10, 16)
    assert from_end.start_date == date(2026, 10, 12)
    assert one_day.start_date == one_day.end_date


def test_duration_only_and_ambiguous_month_remain_missing() -> None:
    duration_only = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(duration_days=5),
    )
    ambiguous_month = merge_requirement_patch(
        PartialTripRequirements(destination="Tokyo"),
        TripRequirementPatch(),
    )

    assert RequirementField.START_DATE in missing_requirement_fields(duration_only)
    assert RequirementField.END_DATE in missing_requirement_fields(duration_only)
    assert ambiguous_month.start_date is None


def test_invalid_date_range_and_duration_mismatch_are_reported() -> None:
    reversed_dates = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(
            start_date=date(2026, 10, 16),
            end_date=date(2026, 10, 12),
        ),
    )
    mismatch = complete_draft(duration_days=4)

    assert invalid_requirement_fields(reversed_dates) == [RequirementField.END_DATE]
    assert RequirementField.DURATION_DAYS in invalid_requirement_fields(mismatch)


def test_date_range_beyond_planning_bound_is_invalid_instead_of_crashing_merge() -> None:
    too_long = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(
            start_date=date(2026, 1, 1),
            end_date=date(2027, 1, 2),
        ),
    )

    assert too_long.duration_days is None
    assert invalid_requirement_fields(too_long) == [RequirementField.END_DATE]


def test_complete_conversion_and_fingerprint_are_stable_and_sensitive() -> None:
    draft = complete_draft()
    equivalent = PartialTripRequirements.model_validate(draft.model_dump(mode="json"))
    changed = complete_draft(destination="Paris")

    assert complete_trip_requirements(draft).destination == "Tokyo"
    assert draft_fingerprint(draft) == draft_fingerprint(equivalent)
    assert draft_fingerprint(draft) != draft_fingerprint(changed)
    assert len(draft_fingerprint(draft)) == 64
