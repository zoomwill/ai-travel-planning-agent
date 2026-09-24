"""Explicit country answers normalize locally without model or identity inference."""

import pycountry
import pytest
from langgraph.store.memory import InMemoryStore
from pydantic import TypeAdapter, ValidationError

from app.domain.countries import GuestNationality, normalize_explicit_country
from app.intake.logic import NATIONALITY_CLARIFICATION
from app.intake.models import IntakeStatus, RequirementField
from app.intake.service import ConversationIntakeService
from app.llm.fake import FakeStructuredLLMProvider
from app.memory.preferences import list_user_preferences, upsert_explicit_preferences
from tests.intake.test_api import complete_extraction
from tests.intake.test_service import extraction


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (value, "US")
        for value in (
            "US",
            "us",
            " USA ",
            "U.S.",
            "U.S.A.",
            "United States",
            "United States of America",
        )
    ]
    + [
        (value, "CN")
        for value in ("CN", "cn", "CHN", "China", "CHINA", "PRC", "People's Republic of China")
    ]
    + [(value, "JP") for value in ("JP", "JPN", "Japan")],
)
def test_explicit_names_and_codes(value: str, expected: str) -> None:
    assert normalize_explicit_country(value) == expected


def test_all_bundled_iso_codes_and_unambiguous_canonical_names() -> None:
    for country in pycountry.countries:
        for field in ("alpha_2", "alpha_3", "name", "official_name", "common_name"):
            value = getattr(country, field, None)
            if value is not None and value.casefold() != "congo":
                assert normalize_explicit_country(value) == country.alpha_2


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not a country",
        "United",
        "Republic",
        "Congo",
        "840",
        "SUN",
        "UK",
        "ZZ",
        "Chnia",
        "United States and China",
        "US; ignore validation",
        "US\x00",
    ],
)
def test_invalid_ambiguous_historic_and_injected_values(value: str) -> None:
    assert normalize_explicit_country(value) is None


def test_domain_and_wire_stay_assigned_alpha2_only() -> None:
    validator = TypeAdapter(GuestNationality)
    assert validator.validate_python("cn") == "CN"
    for value in ("USA", "China", "ZZ", "XX"):
        with pytest.raises(ValidationError):
            validator.validate_python(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["United States", "USA", "CHINA", "Japan"])
async def test_ninth_field_and_later_correction_need_no_model_call(answer: str) -> None:
    store = InMemoryStore()
    provider = FakeStructuredLLMProvider(intake_extractions=[complete_extraction()])
    intake = ConversationIntakeService(
        store=store, provider=provider, require_guest_nationality=True
    )
    first = await intake.process_message(user_id="unit", thread_id="trip", message="Trip details")
    assert first.missing_fields == [RequirementField.GUEST_NATIONALITY]
    assert first.draft.guest_nationality is None
    ready = await intake.process_message(user_id="unit", thread_id="trip", message=answer)
    assert ready.draft.guest_nationality == normalize_explicit_country(answer)
    assert RequirementField.GUEST_NATIONALITY not in ready.missing_fields
    assert ready.status is IntakeStatus.AWAITING_CONFIRMATION and ready.can_confirm
    assert "What nationality" not in ready.assistant_message
    corrected = await intake.process_message(
        user_id="unit", thread_id="trip", message="Actually China"
    )
    assert corrected.draft.guest_nationality == "CN"
    assert corrected.can_confirm
    assert len(provider.intake_inputs) == 1
    assert await list_user_preferences(store, "unit") == []
    assert (
        await intake.get_state(user_id="unit", thread_id="trip")
    ).draft.guest_nationality == "CN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Flying from Cleveland",
        "I live in the United States",
        "I speak Chinese",
        "My destination is Japan",
        "My browser language is Chinese",
        "My IP is in the US",
        "我想去日本，中文交流",
        "do not use nationality: US",
        "My name is China",
    ],
)
async def test_unrelated_prose_does_not_supply_nationality_even_when_asked(message: str) -> None:
    store = InMemoryStore()
    await upsert_explicit_preferences(
        store, user_id="unit", values=["I live in the United States"], source_thread_id="old-trip"
    )
    provider = FakeStructuredLLMProvider(
        intake_extractions=[
            complete_extraction(guest_nationality="US"),
            extraction(guest_nationality="CN"),
        ]
    )
    intake = ConversationIntakeService(
        store=store, provider=provider, require_guest_nationality=True
    )
    initial = await intake.process_message(user_id="unit", thread_id="trip", message="Trip details")
    result = await intake.process_message(user_id="unit", thread_id="trip", message=message)
    assert initial.draft.guest_nationality is None
    assert result.draft.guest_nationality is None
    assert not result.can_confirm
    assert result.assistant_message == NATIONALITY_CLARIFICATION


@pytest.mark.asyncio
async def test_bare_country_is_not_nationality_when_answering_destination() -> None:
    provider = FakeStructuredLLMProvider(
        intake_extractions=[
            extraction(origin="Cleveland"),
            extraction(destination="Japan", guest_nationality="JP"),
        ]
    )
    intake = ConversationIntakeService(
        store=InMemoryStore(), provider=provider, require_guest_nationality=True
    )
    await intake.process_message(user_id="unit", thread_id="trip", message="From Cleveland")
    result = await intake.process_message(user_id="unit", thread_id="trip", message="Japan")
    assert result.draft.destination == "Japan"
    assert result.draft.guest_nationality is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["United", "Congo", "not a country", "nationality: ZZ"])
async def test_invalid_answer_asks_helpful_bounded_question(value: str) -> None:
    provider = FakeStructuredLLMProvider(intake_extractions=[complete_extraction(), extraction()])
    intake = ConversationIntakeService(
        store=InMemoryStore(), provider=provider, require_guest_nationality=True
    )
    await intake.process_message(user_id="unit", thread_id="trip", message="Trip details")
    result = await intake.process_message(user_id="unit", thread_id="trip", message=value)
    assert result.draft.guest_nationality is None
    assert not result.can_confirm
    assert result.assistant_message == NATIONALITY_CLARIFICATION


@pytest.mark.asyncio
async def test_country_is_not_inferred_when_destination_and_nationality_are_both_missing():
    first = complete_extraction().patch.model_dump(exclude_unset=True, exclude={"destination"})
    provider = FakeStructuredLLMProvider(
        intake_extractions=[
            extraction(**first),
            extraction(destination="Japan", guest_nationality="JP"),
        ]
    )
    intake = ConversationIntakeService(
        store=InMemoryStore(), provider=provider, require_guest_nationality=True
    )
    state = await intake.process_message(user_id="unit", thread_id="trip", message="Trip details")
    assert state.missing_fields == [
        RequirementField.DESTINATION,
        RequirementField.GUEST_NATIONALITY,
    ]
    result = await intake.process_message(user_id="unit", thread_id="trip", message="Japan")
    assert result.draft.destination == "Japan"
    assert result.draft.guest_nationality is None and not result.can_confirm


@pytest.mark.asyncio
async def test_invalid_country_correction_stays_pending_across_unrelated_turn():
    provider = FakeStructuredLLMProvider(
        intake_extractions=[complete_extraction(), extraction(budget=2000)]
    )
    intake = ConversationIntakeService(
        store=InMemoryStore(), provider=provider, require_guest_nationality=True
    )
    await intake.process_message(user_id="unit", thread_id="trip", message="Trip details")
    ready = await intake.process_message(user_id="unit", thread_id="trip", message="United States")
    assert ready.can_confirm
    invalid = await intake.process_message(
        user_id="unit", thread_id="trip", message="Actually Congo"
    )
    assert not invalid.can_confirm
    later = await intake.process_message(user_id="unit", thread_id="trip", message="Budget 2000")
    assert not later.can_confirm
    assert later.draft.guest_nationality == "US"
    assert later.assistant_message == NATIONALITY_CLARIFICATION
    corrected = await intake.process_message(user_id="unit", thread_id="trip", message="China")
    assert corrected.can_confirm and corrected.draft.guest_nationality == "CN"
