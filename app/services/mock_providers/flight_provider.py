"""Deterministic mock flight search."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from app.domain.models import FlightOption, TripRequirements
from app.services.mock_providers._shared import mock_amount, stable_code, validate_trip_route


def search_flights(requirements: TripRequirements) -> list[FlightOption]:
    """Return two repeatable flight options for valid trip requirements."""

    validate_trip_route(requirements, "search_flights")
    route_code = stable_code(requirements.origin, requirements.destination)
    duration = 120 + route_code % 241
    departure = datetime.combine(requirements.start_date, time(hour=8, minute=30))
    base_cny_price = _base_flight_price(requirements, route_code)

    first = FlightOption(
        flight_number=f"MK{100 + route_code % 900}",
        airline="Mock Pacific",
        origin=requirements.origin,
        destination=requirements.destination,
        departure_time=departure,
        arrival_time=departure + timedelta(minutes=duration),
        duration_minutes=duration,
        price=mock_amount(requirements.currency, base_cny_price),
        currency=requirements.currency,
    )
    second_departure = departure + timedelta(hours=5)
    second_duration = duration + 35
    second = FlightOption(
        flight_number=f"MC{100 + (route_code + 137) % 900}",
        airline="Mock Connect",
        origin=requirements.origin,
        destination=requirements.destination,
        departure_time=second_departure,
        arrival_time=second_departure + timedelta(minutes=second_duration),
        duration_minutes=second_duration,
        price=mock_amount(requirements.currency, base_cny_price * Decimal("0.92")),
        currency=requirements.currency,
    )
    return [first, second]


def _base_flight_price(requirements: TripRequirements, route_code: int) -> Decimal:
    """Return a stable mock base price, including the source's Tokyo example."""

    route = (requirements.origin.casefold(), requirements.destination.casefold())
    if route == ("shanghai", "tokyo"):
        return Decimal("1800.00")
    return Decimal(1200 + route_code % 901)
