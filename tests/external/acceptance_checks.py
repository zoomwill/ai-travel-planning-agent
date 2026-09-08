"""Value-free acceptance assertions shared by offline and gated real tests."""

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from app.graphs.state import TravelPlanState

_SECRET = re.compile(
    r"(?i)(?:\b(?:duffel_(?:test|live)_|sandbox_|sand_|prod_|sk-)[A-Za-z0-9_-]{12,}"
    r"|\bbearer\s+\S+|(?:postgres(?:ql)?|rediss?)://\S+"
    r"|\b(?:authorization|x-api-key|api_key|access_token)\s*[:=]\s*\S+)"
)
_RAW_FIELDS = {
    "authorization",
    "x-api-key",
    "api_key",
    "access_token",
    "roomtypes",
    "retailrate",
    "offerretailrate",
    "raw_response",
    "raw_completion",
    "completion",
    "prompt",
}


class AcceptanceFailure(RuntimeError):
    """Contain only a hard-coded safe check name, never inspected values."""


def require(condition: bool, check: str) -> None:
    """Fail without pytest's potentially sensitive assertion-value expansion."""
    if not condition:
        raise AcceptanceFailure(check)


def check_public_tree(value: object) -> None:
    """Reject secrets, raw vendor envelopes and non-domain runtime objects recursively."""
    if isinstance(value, BaseModel):
        require(type(value).__module__.startswith("app.domain."), "non-domain model in state")
        check_public_tree(value.model_dump(mode="json"))
    elif isinstance(value, dict):
        for key, item in value.items():
            require(
                isinstance(key, str) and key.casefold() not in _RAW_FIELDS,
                "raw field in public data",
            )
            check_public_tree(key)
            check_public_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_public_tree(item)
    elif isinstance(value, Enum):
        check_public_tree(value.value)
    elif isinstance(value, str):
        require(_SECRET.search(value) is None, "credential-shaped content in public data")
    else:
        require(
            value is None or isinstance(value, (bool, int, float, Decimal, date, datetime)),
            "runtime object in public data",
        )


def check_state(values: dict, flight_limit: int, hotel_limit: int) -> None:
    """Audit application channels, not LangGraph's internal checkpoint transport metadata."""
    public = {key: value for key, value in values.items() if key in TravelPlanState.__annotations__}
    check_public_tree(public)
    limits = {"flights": flight_limit, "hotels": hotel_limit}
    for result in public.get("search_results", []):
        if result["kind"] in limits:
            require(len(result["data"]) <= limits[result["kind"]], "checkpoint candidate cap")
