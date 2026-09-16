"""Explicitly unavailable until local-route scope can be verified."""

from app.domain.models import RouteSummary
from app.services.mock_providers._shared import require_distinct_places


class RouteUnavailableError(RuntimeError):
    """No verified route data exists; this is a non-critical search limitation."""


def get_route(origin: str, destination: str) -> RouteSummary:
    """Reject unsupported routes without guessing geography, duration, or cost."""

    require_distinct_places(origin, destination, "get_route")
    raise RouteUnavailableError("Route information unavailable: no verified route coverage.")
