"""Safe external-provider errors that never retain raw response data."""

from dataclasses import dataclass
from typing import Literal, TypeAlias

DuffelErrorCode: TypeAlias = Literal[
    "duffel_not_configured",
    "duffel_invalid_environment",
    "duffel_authentication_failed",
    "duffel_rate_limited",
    "duffel_timeout",
    "duffel_transport_error",
    "duffel_invalid_response",
    "duffel_no_flight_offers",
    "duffel_no_stay_results",
    "duffel_stays_access_denied",
    "duffel_location_not_found",
    "duffel_unsupported_request",
    "duffel_provider_error",
]


class DuffelError(RuntimeError):
    """Carry only a stable code and safe recovery hint across app boundaries."""

    def __init__(self, code: DuffelErrorCode, *, recoverable: bool = False) -> None:
        self.code = code
        self.recoverable = recoverable
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DuffelSchemaIssue:
    """One value-free schema location and Pydantic error type."""

    loc: str
    type: str


class DuffelSchemaError(DuffelError):
    """Retain only bounded, non-value diagnostics for a schema mismatch."""

    def __init__(
        self,
        operation: str,
        error_count: int,
        issues: tuple[DuffelSchemaIssue, ...],
    ) -> None:
        self.operation = operation
        self.error_count = error_count
        self.issues = issues
        super().__init__("duffel_invalid_response")
