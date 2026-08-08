"""Deterministic mock route estimates."""

from decimal import Decimal

from app.domain.models import Currency, RouteSummary, TransportMode
from app.services.mock_providers._shared import require_distinct_places, stable_code


def get_route(origin: str, destination: str) -> RouteSummary:
    """Return a repeatable public-transit estimate between two places."""

    require_distinct_places(origin, destination, "get_route")
    route_code = stable_code(origin, destination)
    return RouteSummary(
        origin=origin,
        destination=destination,
        transport_mode=TransportMode.PUBLIC_TRANSIT,
        duration_minutes=15 + route_code % 91,
        estimated_cost=Decimal(8 + route_code % 43),
        currency=Currency.CNY,
    )
