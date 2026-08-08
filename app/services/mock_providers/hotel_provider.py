"""Deterministic mock hotel search."""

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.domain.models import HotelOption, TripRequirements
from app.services.mock_providers._shared import mock_amount, stable_code, validate_trip_route

HotelTemplate = tuple[str, float, Decimal, float, tuple[str, ...]]

_CITY_HOTELS: Final[Mapping[str, tuple[HotelTemplate, ...]]] = MappingProxyType(
    {
        "tokyo": (
            (
                "Tokyo Central Hotel",
                4.5,
                Decimal("780.00"),
                1.2,
                ("Wi-Fi", "breakfast", "laundry"),
            ),
            (
                "Tokyo Garden Stay",
                4.2,
                Decimal("620.00"),
                2.8,
                ("Wi-Fi", "family rooms"),
            ),
        ),
        "shanghai": (
            (
                "Shanghai Riverside Hotel",
                4.6,
                Decimal("720.00"),
                1.5,
                ("Wi-Fi", "breakfast", "fitness room"),
            ),
            (
                "Shanghai Lane Stay",
                4.1,
                Decimal("510.00"),
                3.1,
                ("Wi-Fi", "laundry"),
            ),
        ),
    }
)


def search_hotels(requirements: TripRequirements) -> list[HotelOption]:
    """Return repeatable hotel options in the requested destination."""

    validate_trip_route(requirements, "search_hotels")
    templates = _CITY_HOTELS.get(requirements.destination.casefold())
    if templates is None:
        templates = _generic_templates(requirements.destination)

    return [
        HotelOption(
            name=name,
            city=requirements.destination,
            rating=rating,
            price_per_night=mock_amount(requirements.currency, cny_price),
            currency=requirements.currency,
            distance_to_center_km=distance,
            amenities=list(amenities),
        )
        for name, rating, cny_price, distance, amenities in templates
    ]


def _generic_templates(city: str) -> tuple[HotelTemplate, ...]:
    """Build stable fallback hotels for any nonblank destination."""

    city_code = stable_code(city)
    central_price = Decimal(560 + city_code % 241)
    return (
        (
            f"{city} Central Mock Hotel",
            4.0 + (city_code % 6) / 10,
            central_price,
            1.0 + (city_code % 15) / 10,
            ("Wi-Fi", "breakfast"),
        ),
        (
            f"{city} Quiet Mock Stay",
            3.8 + (city_code % 5) / 10,
            central_price * Decimal("0.78"),
            2.5 + (city_code % 20) / 10,
            ("Wi-Fi", "laundry"),
        ),
    )
