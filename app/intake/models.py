"""Strict JSON-safe models for conversational requirement collection."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from app.domain.countries import GuestNationality
from app.domain.models import Currency, TripRequirements
from app.memory.preferences import clean_preference_value, normalize_preference

PreferenceText = Annotated[str, Field(min_length=1, max_length=300)]


class IntakeModel(BaseModel):
    """Reject unknown fields and normalize strings at the intake boundary."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class RequirementField(StrEnum):
    """Bounded field names used for deterministic validation and metrics."""

    ORIGIN = "origin"
    DESTINATION = "destination"
    START_DATE = "start_date"
    END_DATE = "end_date"
    DURATION_DAYS = "duration_days"
    BUDGET = "budget"
    CURRENCY = "currency"
    TRAVELERS = "travelers"
    PREFERENCES = "preferences"
    GUEST_NATIONALITY = "guest_nationality"


class IntakeStatus(StrEnum):
    """Public lifecycle of one recoverable intake draft."""

    COLLECTING = "collecting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PLANNING = "planning"
    PLANNED = "planned"


class ConversationRole(StrEnum):
    """Only user-visible message roles stored in PostgreSQL Store."""

    USER = "user"
    ASSISTANT = "assistant"


class PartialTripRequirements(IntakeModel):
    """An intake-only draft whose planning fields may still be absent."""

    origin: str | None = Field(default=None, min_length=1, max_length=120)
    destination: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int | None = Field(default=None, strict=True, ge=1, le=366)
    budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Currency | None = None
    travelers: int | None = Field(default=None, strict=True, ge=1, le=100)
    guest_nationality: GuestNationality | None = None
    preferences: list[PreferenceText] = Field(default_factory=list, max_length=20)

    @field_validator("preferences")
    @classmethod
    def normalize_preferences(cls, values: list[str]) -> list[str]:
        """Clean and case-insensitively deduplicate current-trip preferences."""

        unique: dict[str, str] = {}
        for value in values:
            cleaned = clean_preference_value(value)
            normalized = normalize_preference(cleaned)
            if normalized:
                unique.setdefault(normalized, cleaned)
        return list(unique.values())


class TripRequirementPatch(IntakeModel):
    """One strict incremental change returned by the semantic extractor."""

    origin: str | None = Field(default=None, min_length=1, max_length=120)
    destination: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    duration_days: StrictInt | None = Field(default=None, ge=1, le=366)
    budget: StrictInt | StrictFloat | None = Field(default=None, gt=0, le=1_000_000_000)
    currency: Currency | None = None
    travelers: StrictInt | None = Field(default=None, ge=1, le=100)
    guest_nationality: GuestNationality | None = None
    preferences_add: list[PreferenceText] = Field(default_factory=list, max_length=20)
    preferences_remove: list[PreferenceText] = Field(default_factory=list, max_length=20)
    clear_fields: list[RequirementField] = Field(default_factory=list, max_length=10)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def require_exact_iso_date(cls, value: object) -> object:
        """Reject timestamps and non-ISO date shapes at the model-output boundary."""

        if value is None or isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise ValueError("date must use exact YYYY-MM-DD form") from None
            if len(value) == 10 and parsed.isoformat() == value:
                return value
        raise ValueError("date must use exact YYYY-MM-DD form")

    @field_validator("budget")
    @classmethod
    def require_currency_precision(cls, value: int | float | None) -> int | float | None:
        """Reject model numbers that cannot become the two-decimal draft budget."""

        if value is None:
            return value
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.quantize(Decimal("0.01")):
            raise ValueError("budget may have at most two decimal places")
        return value

    @model_validator(mode="after")
    def validate_patch_operations(self) -> Self:
        """Reject null assignments, duplicate operations, and conflicting changes."""

        optional_values = {
            "origin",
            "destination",
            "start_date",
            "end_date",
            "duration_days",
            "budget",
            "currency",
            "travelers",
            "guest_nationality",
        }
        for field_name in self.model_fields_set & optional_values:
            if getattr(self, field_name) is None:
                raise ValueError("use clear_fields rather than null to clear a field")

        if len(self.clear_fields) != len(set(self.clear_fields)):
            raise ValueError("clear_fields cannot contain duplicates")
        assigned = {
            RequirementField(field_name) for field_name in self.model_fields_set & optional_values
        }
        if assigned & set(self.clear_fields):
            raise ValueError("a field cannot be assigned and cleared in the same patch")

        added = {normalize_preference(value) for value in self.preferences_add}
        removed = {normalize_preference(value) for value in self.preferences_remove}
        if added & removed:
            raise ValueError("a preference cannot be added and removed in the same patch")
        return self


class ConversationMessage(IntakeModel):
    """One redacted, user-visible message persisted for recovery."""

    message_id: str = Field(pattern=r"^msg_[0-9a-f]{24}$")
    role: ConversationRole
    content: str = Field(min_length=1, max_length=4000)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Keep persisted timestamps timezone-aware and normalized to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if value.utcoffset() != timedelta(0):
            raise ValueError("created_at must use UTC")
        return value.astimezone(UTC)


class ConversationIntakeState(IntakeModel):
    """Complete recoverable conversation state stored outside graph checkpoints."""

    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=64)
    status: IntakeStatus = IntakeStatus.COLLECTING
    assistant_message: str = Field(min_length=1, max_length=1000)
    draft: PartialTripRequirements = Field(default_factory=PartialTripRequirements)
    missing_fields: list[RequirementField] = Field(default_factory=list, max_length=8)
    invalid_fields: list[RequirementField] = Field(default_factory=list, max_length=10)
    draft_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    messages: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    turn_count: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    plan_available: bool = False
    created_at: datetime
    updated_at: datetime
    planned_at: datetime | None = None

    @property
    def can_confirm(self) -> bool:
        """Return true only while a complete current draft awaits explicit consent."""

        return self.status == IntakeStatus.AWAITING_CONFIRMATION


def new_intake_state(
    *,
    thread_id: str,
    user_id: str,
    now: datetime,
    draft_fingerprint: str,
) -> ConversationIntakeState:
    """Create an empty state with one deterministic beginner-facing message."""

    return ConversationIntakeState(
        thread_id=thread_id,
        user_id=user_id,
        assistant_message="Tell me where you would like to travel.",
        draft_fingerprint=draft_fingerprint,
        created_at=now,
        updated_at=now,
    )


def complete_trip_requirements(draft: PartialTripRequirements) -> TripRequirements:
    """Convert a complete intake draft through the unchanged domain validator."""

    values = draft.model_dump(exclude={"duration_days"}, exclude_none=True)
    return TripRequirements.model_validate(values)
