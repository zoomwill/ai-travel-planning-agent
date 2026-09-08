"""Value-free, stable LiteAPI errors."""

from typing import Literal, TypeAlias

from app.external.duffel.errors import DuffelSchemaIssue

LiteAPIErrorCode: TypeAlias = Literal[
    "liteapi_not_configured",
    "liteapi_authentication_failed",
    "liteapi_rate_limited",
    "liteapi_timeout",
    "liteapi_transport_error",
    "liteapi_invalid_response",
    "liteapi_no_hotel_rates",
    "liteapi_invalid_guest_nationality",
    "liteapi_unsupported_request",
    "liteapi_provider_error",
]


class LiteAPIError(RuntimeError):
    """Carry a safe code, never a request, response, or credential."""

    def __init__(self, code: LiteAPIErrorCode, *, recoverable: bool = False) -> None:
        self.code = code
        self.recoverable = recoverable
        super().__init__(code)


class LiteAPISchemaError(LiteAPIError):
    """Expose bounded structural diagnostics only."""

    def __init__(self, count: int, issues: tuple[DuffelSchemaIssue, ...]) -> None:
        self.error_count = count
        self.issues = issues
        super().__init__("liteapi_invalid_response")
