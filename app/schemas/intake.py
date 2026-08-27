"""Validated public HTTP models for conversational trip intake."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.intake.models import (
    ConversationIntakeState,
    ConversationMessage,
    IntakeStatus,
    PartialTripRequirements,
    RequirementField,
)

PreferenceText = Annotated[str, Field(min_length=1, max_length=300)]


class IntakeRequestModel(BaseModel):
    """Apply strict request validation to every conversational mutation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationMessageRequest(IntakeRequestModel):
    """One bounded natural-language turn for an explicit local user."""

    user_id: str
    message: str = Field(min_length=1, max_length=4000)
    start_new_trip: bool = False


class ConversationConfirmRequest(IntakeRequestModel):
    """Explicit consent tied to the exact current draft fingerprint."""

    user_id: str
    draft_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    remember_preferences: list[PreferenceText] = Field(default_factory=list, max_length=50)


class ConversationResetRequest(IntakeRequestModel):
    """Identify the one user namespace whose current intake should reset."""

    user_id: str


class ConversationResponse(BaseModel):
    """Safe public projection with no prompt, completion, SDK, or Store metadata."""

    thread_id: str
    user_id: str
    status: IntakeStatus
    assistant_message: str
    draft: PartialTripRequirements
    missing_fields: list[RequirementField]
    invalid_fields: list[RequirementField]
    can_confirm: bool
    draft_fingerprint: str
    messages: list[ConversationMessage]
    turn_count: int = Field(ge=0)
    version: int = Field(ge=0)
    plan_available: bool

    @classmethod
    def from_state(cls, state: ConversationIntakeState) -> "ConversationResponse":
        """Copy only allowlisted user-visible fields from persisted state."""

        return cls(
            thread_id=state.thread_id,
            user_id=state.user_id,
            status=state.status,
            assistant_message=state.assistant_message,
            draft=state.draft,
            missing_fields=state.missing_fields,
            invalid_fields=state.invalid_fields,
            can_confirm=state.can_confirm,
            draft_fingerprint=state.draft_fingerprint,
            messages=state.messages,
            turn_count=state.turn_count,
            version=state.version,
            plan_available=state.plan_available,
        )
