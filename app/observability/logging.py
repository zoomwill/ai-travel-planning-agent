"""Loguru configuration with a small, safe JSON schema."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from threading import Lock
from typing import Any, TextIO

from loguru import logger

from app.observability.context import get_request_id

BACKTRACE_ENABLED = False
DIAGNOSE_ENABLED = False

_PUBLIC_FIELDS = (
    "event",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "component",
    "backend_mode",
    "node",
    "search_kind",
    "tool",
    "review_round",
    "outcome",
    "error_code",
    "thread_ref",
    "user_ref",
    "role",
    "model",
    "input_token_count",
    "output_token_count",
    "fallback",
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization|cookie)\s*[:=]\s*[^\r\n]*"),
    re.compile(r"(?i)(token|api[_-]?key|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bsk-(?:ws-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(postgres(?:ql)?(?:\+[A-Za-z0-9_.-]+)?|redis)://[^\s]+"),
)


def redact_text(value: str) -> str:
    """Remove common credential and connection-string shapes from log text."""

    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class JsonLogSink:
    """Serialize one Loguru record into one compact JSON object."""

    def __init__(self, target: TextIO) -> None:
        self._target = target

    def __call__(self, message: Any) -> None:
        """Write an allowlisted record without recursively calling Loguru."""

        record = message.record
        payload: dict[str, object] = {
            "timestamp": record["time"].astimezone(UTC).isoformat(),
            "level": record["level"].name,
            "message": redact_text(record["message"]),
        }
        extra = record["extra"]
        for field in _PUBLIC_FIELDS:
            value = extra.get(field)
            if value is not None:
                payload[field] = redact_text(value) if isinstance(value, str) else value
        if "request_id" not in payload:
            request_id = get_request_id()
            if request_id is not None:
                payload["request_id"] = request_id
        self._target.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._target.flush()


@dataclass(frozen=True, slots=True)
class LoggingLease:
    """One caller's ownership claim on the process-wide application sink."""

    lease_id: int


class _LoggingLifecycle:
    """Reference-count one compatible Loguru sink across overlapping app lifespans."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._handler_id: int | None = None
        self._active_leases: set[int] = set()
        self._next_lease_id = 1
        self._initialized = False
        self._level: str | None = None
        self._target: TextIO | None = None
        self._sink_factory: Callable[[TextIO], JsonLogSink] | None = None

    def acquire(
        self,
        level: str,
        target: TextIO,
        sink_factory: Callable[[TextIO], JsonLogSink],
    ) -> LoggingLease:
        """Install one shared sink or safely join an identical active configuration."""

        normalized_level = level.upper()
        with self._lock:
            if self._handler_id is None:
                if not self._initialized:
                    logger.remove()
                    self._initialized = True
                self._handler_id = logger.add(
                    sink_factory(target),
                    level=normalized_level,
                    backtrace=BACKTRACE_ENABLED,
                    diagnose=DIAGNOSE_ENABLED,
                    enqueue=False,
                    catch=True,
                )
                self._level = normalized_level
                self._target = target
                self._sink_factory = sink_factory
            elif (
                normalized_level != self._level
                or target is not self._target
                or sink_factory is not self._sink_factory
            ):
                raise RuntimeError(
                    "overlapping application lifespans must share one Loguru configuration"
                )

            lease = LoggingLease(self._next_lease_id)
            self._next_lease_id += 1
            self._active_leases.add(lease.lease_id)
            return lease

    def release(self, lease: LoggingLease) -> bool:
        """Release once and remove the sink only after the final active lifespan."""

        with self._lock:
            if lease.lease_id not in self._active_leases:
                return False
            self._active_leases.remove(lease.lease_id)
            if self._active_leases:
                return False

            handler_id = self._handler_id
            self._handler_id = None
            self._level = None
            self._target = None
            self._sink_factory = None
            if handler_id is not None:
                try:
                    logger.remove(handler_id)
                except ValueError:
                    pass
            return True


_LOGGING_LIFECYCLE = _LoggingLifecycle()


def configure_logging(
    level: str,
    *,
    target: TextIO | None = None,
    sink_factory: Callable[[TextIO], JsonLogSink] = JsonLogSink,
) -> LoggingLease:
    """Acquire the single process-wide application sink for one lifespan."""

    resolved_target = target if target is not None else sys.stderr
    return _LOGGING_LIFECYCLE.acquire(
        level,
        resolved_target,
        sink_factory,
    )


async def shutdown_logging(lease: LoggingLease) -> None:
    """Release idempotently and flush after the final active lifespan exits."""

    if _LOGGING_LIFECYCLE.release(lease):
        await logger.complete()


def log_event(event: str, message: str, **fields: Any) -> None:
    """Emit one schema-bound informational event without raw objects."""

    logger.bind(event=event, **fields).info(message)
