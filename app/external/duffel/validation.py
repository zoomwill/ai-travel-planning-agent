"""Value-free validation diagnostics for untrusted Duffel responses."""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from app.external.duffel.errors import DuffelSchemaError, DuffelSchemaIssue
from app.observability.logging import log_event

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_MAX_REPORTED_ISSUES = 20


def validate_duffel_response(
    model: type[ResponseModel],
    payload: object,
    *,
    operation: str,
) -> ResponseModel:
    """Validate a response and expose only schema paths and error types on failure."""

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        issues = tuple(
            _safe_issue(item)
            for item in exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:_MAX_REPORTED_ISSUES]
        )
        for issue in issues:
            log_event(
                "duffel_schema_mismatch",
                "Duffel response did not match the validated projection.",
                provider="duffel",
                operation=operation,
                validation_error_count=exc.error_count(),
                validation_error_loc=issue.loc,
                validation_error_type=issue.type,
            )
        raise DuffelSchemaError(operation, exc.error_count(), issues) from None


def _safe_issue(error: ErrorDetails) -> DuffelSchemaIssue:
    """Reduce one Pydantic error to allowlisted structural metadata."""

    raw_loc = error.get("loc", ())
    loc = ".".join(_safe_part(part) for part in raw_loc) or "response"
    error_type = _safe_text(error.get("type"), fallback="validation_error")
    return DuffelSchemaIssue(loc=loc, type=error_type)


def _safe_part(value: str | int) -> str:
    text = str(value)
    return text if _SAFE_PART.fullmatch(text) else "field"


def _safe_text(value: object, *, fallback: str) -> str:
    text = value if isinstance(value, str) else ""
    return text if _SAFE_PART.fullmatch(text) else fallback
