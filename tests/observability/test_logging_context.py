"""Safe structured logging and asynchronous correlation tests."""

import asyncio
import json
from io import StringIO

import pytest

from app.observability.context import (
    choose_request_id,
    get_request_id,
    pseudonymous_ref,
    reset_request_id,
    set_request_id,
    valid_request_id,
)
from app.observability.logging import (
    BACKTRACE_ENABLED,
    DIAGNOSE_ENABLED,
    configure_logging,
    log_event,
    redact_text,
    shutdown_logging,
)


def test_request_id_validation_and_pseudonymous_references() -> None:
    assert valid_request_id("caller-id:123")
    assert choose_request_id("caller-id:123") == "caller-id:123"
    generated = choose_request_id("invalid id with spaces")
    assert generated != "invalid id with spaces"
    assert valid_request_id(generated)
    assert not valid_request_id("x" * 65)

    first = pseudonymous_ref("private-user", kind="user")
    assert first == pseudonymous_ref("private-user", kind="user")
    assert first != pseudonymous_ref("another-user", kind="user")
    assert "private-user" not in first


@pytest.mark.asyncio
async def test_contextvars_do_not_cross_concurrent_tasks() -> None:
    ready = asyncio.Event()
    values: dict[str, str | None] = {}

    async def worker(name: str) -> None:
        token = set_request_id(name)
        try:
            if name == "request-a":
                ready.set()
                await asyncio.sleep(0)
            else:
                await ready.wait()
            values[name] = get_request_id()
        finally:
            reset_request_id(token)

    await asyncio.gather(worker("request-a"), worker("request-b"))
    assert values == {"request-a": "request-a", "request-b": "request-b"}
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_json_log_schema_redacts_secrets_without_traceback() -> None:
    output = StringIO()
    handler = configure_logging("INFO", target=output)
    token = set_request_id("safe-request")
    try:
        log_event(
            "test_event",
            "Authorization=Bearer hidden postgresql://user:pass@localhost/db",
            component="test",
            outcome="success",
            ignored_private_field="must-not-appear",
        )
    finally:
        reset_request_id(token)
        await shutdown_logging(handler)

    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "test_event"
    assert payload["request_id"] == "safe-request"
    assert payload["component"] == "test"
    assert "hidden" not in lines[0]
    assert "postgresql://" not in lines[0]
    assert "ignored_private_field" not in lines[0]
    assert "exception" not in payload
    assert BACKTRACE_ENABLED is False
    assert DIAGNOSE_ENABLED is False


@pytest.mark.asyncio
async def test_overlapping_logging_leases_keep_one_sink_until_final_shutdown() -> None:
    output = StringIO()
    first = configure_logging("INFO", target=output)
    second = configure_logging("INFO", target=output)
    try:
        log_event("both_active", "Both application lifespans are active.")
        await shutdown_logging(second)
        await shutdown_logging(second)
        log_event("first_still_active", "The first application still owns the shared sink.")
    finally:
        await shutdown_logging(second)
        await shutdown_logging(first)

    payloads = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [payload["event"] for payload in payloads] == [
        "both_active",
        "first_still_active",
    ]


def test_standalone_redaction_covers_common_secret_shapes() -> None:
    private = (
        "Cookie: session=hidden; theme=private\n"
        "password=hunter2 token=abc redis://:secret@localhost/0 "
        "postgresql+psycopg://user:driver-secret@localhost/db "
        "sk-ws-not-a-real-key-12345"
    )
    redacted = redact_text(private)
    assert all(
        value not in redacted
        for value in (
            "hidden",
            "private",
            "hunter2",
            "abc",
            "redis://",
            "secret",
            "postgresql+psycopg://",
            "driver-secret",
            "sk-ws-not-a-real-key-12345",
        )
    )
