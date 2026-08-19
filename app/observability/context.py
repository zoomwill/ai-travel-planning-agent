"""Request correlation and pseudonymous references for safe logs."""

from __future__ import annotations

import hashlib
import re
import uuid
from contextvars import ContextVar, Token

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def valid_request_id(value: str | None) -> bool:
    """Return true only for bounded header values safe to place in logs."""

    return value is not None and _REQUEST_ID_PATTERN.fullmatch(value) is not None


def choose_request_id(value: str | None) -> str:
    """Keep a valid caller ID or generate a random UUID for this request."""

    if value is not None and valid_request_id(value):
        return value
    return str(uuid.uuid4())


def set_request_id(value: str) -> Token[str | None]:
    """Bind one request ID to the current asynchronous context."""

    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous asynchronous request context."""

    _request_id.reset(token)


def get_request_id() -> str | None:
    """Return the current request ID without inventing a new one."""

    return _request_id.get()


def pseudonymous_ref(value: str, *, kind: str) -> str:
    """Create a stable one-way reference; this is not anonymization."""

    digest = hashlib.sha256(f"travel-planner:p13:{kind}:{value}".encode()).hexdigest()[:16]
    prefix = "usr" if kind == "user" else "thr"
    return f"{prefix}_{digest}"
