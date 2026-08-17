"""Strict public and internal models used by the P12 SSE layer."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class StreamEventType(StrEnum):
    """Stable business event names available to SSE clients."""

    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    SEARCH_STARTED = "search_started"
    SEARCH_COMPLETED = "search_completed"
    SEARCH_FAILED = "search_failed"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    REVIEW_COMPLETED = "review_completed"
    REVISION_STARTED = "revision_started"
    PLAN_COMPLETED = "plan_completed"
    ERROR = "error"


class StreamEventStatus(StrEnum):
    """Small status vocabulary shared by every business event."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class StreamingModel(BaseModel):
    """Reject accidental fields in every streaming model."""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class StreamEventDraft(StreamingModel):
    """Safe event content before a connection assigns identity and time."""

    event_type: StreamEventType
    node: str = Field(min_length=1, max_length=64)
    status: StreamEventStatus
    message: str = Field(min_length=1, max_length=500)
    data: dict[str, JsonValue] = Field(default_factory=dict)


class StreamBusinessEvent(StreamEventDraft):
    """One complete public business event sent through SSE."""

    event_id: int = Field(ge=1)
    thread_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        """Require a timezone-aware UTC timestamp."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        """Keep the SSE ID and public sequence identical."""

        if self.event_id != self.sequence:
            raise ValueError("event_id must equal sequence")
        return self


class StreamHeartbeat(StreamingModel):
    """Transport keepalive that deliberately has no business sequence."""

    comment: str = Field(default="ping", min_length=1, max_length=32)
