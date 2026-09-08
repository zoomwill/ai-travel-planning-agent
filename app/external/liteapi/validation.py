"""Safe LiteAPI diagnostics using the established Duffel projection policy."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.external.duffel.validation import _safe_issue
from app.external.liteapi.errors import LiteAPISchemaError
from app.observability.logging import log_event

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def validate_liteapi_response(model: type[ResponseModel], payload: object) -> ResponseModel:
    """Validate consumed fields and log only paths/types, never values."""

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        issues = tuple(
            _safe_issue(item)
            for item in exc.errors(include_url=False, include_context=False, include_input=False)[
                :20
            ]
        )
        for issue in issues:
            log_event(
                "liteapi_schema_mismatch",
                "Hotel response projection validation failed.",
                provider="liteapi",
                operation="hotel_rates",
                validation_error_count=exc.error_count(),
                validation_error_loc=issue.loc,
                validation_error_type=issue.type,
            )
        raise LiteAPISchemaError(exc.error_count(), issues) from None
