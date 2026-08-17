"""Validation tests for public streaming models."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.streaming.models import (
    StreamBusinessEvent,
    StreamEventStatus,
    StreamEventType,
)


def event(timestamp: datetime) -> StreamBusinessEvent:
    """Create one minimal complete business event."""

    return StreamBusinessEvent(
        event_id=1,
        thread_id="thread-a",
        event_type=StreamEventType.RUN_STARTED,
        node="agent_runtime",
        sequence=1,
        timestamp=timestamp,
        status=StreamEventStatus.STARTED,
        message="开始规划。",
        data={"text": '东京 "摄影"\n路线'},
    )


def test_business_event_is_utc_json_safe_and_preserves_unicode() -> None:
    value = event(datetime(2026, 8, 17, 8, 30, tzinfo=UTC))
    payload = value.model_dump(mode="json")

    assert payload["timestamp"] == "2026-08-17T08:30:00Z"
    assert payload["message"] == "开始规划。"
    assert payload["data"] == {"text": '东京 "摄影"\n路线'}
    assert value.event_id == value.sequence == 1


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 8, 17, 8, 30),
        datetime(2026, 8, 17, 8, 30, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_business_event_rejects_naive_or_non_utc_timestamp(timestamp: datetime) -> None:
    with pytest.raises(ValidationError):
        event(timestamp)


def test_business_event_requires_event_id_to_match_sequence() -> None:
    with pytest.raises(ValidationError, match="event_id must equal sequence"):
        event(datetime(2026, 8, 17, 8, 30, tzinfo=UTC)).model_copy(
            update={"event_id": 2},
            deep=True,
        ).__class__.model_validate(
            {
                **event(datetime(2026, 8, 17, 8, 30, tzinfo=UTC)).model_dump(),
                "event_id": 2,
            }
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"sse_heartbeat_seconds": 0},
        {"sse_heartbeat_seconds": 15},
        {"sse_queue_maxsize": 0},
        {"sse_queue_maxsize": 1025},
    ],
)
def test_sse_settings_reject_unsafe_bounds(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)
