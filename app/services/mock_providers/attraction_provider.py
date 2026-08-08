"""Deterministic mock attraction search."""

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.domain.models import Attraction, TripRequirements
from app.services.mock_providers._shared import mock_amount, stable_code, validate_trip_route

AttractionTemplate = tuple[str, str, str, Decimal, str]

_CITY_ATTRACTIONS: Final[Mapping[str, tuple[AttractionTemplate, ...]]] = MappingProxyType(
    {
        "tokyo": (
            (
                "Asakusa Heritage Walk",
                "culture",
                "A mock self-guided walk through historic streets.",
                Decimal("0.00"),
                "09:00-18:00",
            ),
            (
                "Shinjuku Observation Deck",
                "viewpoint",
                "A mock city-view stop above the Shinjuku district.",
                Decimal("80.00"),
                "10:00-21:00",
            ),
            (
                "Ueno Museum Quarter",
                "museum",
                "A mock half-day collection of cultural exhibits.",
                Decimal("120.00"),
                "09:30-17:00",
            ),
        ),
        "shanghai": (
            (
                "The Bund Riverside Walk",
                "landmark",
                "A mock architecture walk beside the Huangpu River.",
                Decimal("0.00"),
                "Open all day",
            ),
            (
                "Yu Garden Cultural Visit",
                "garden",
                "A mock visit focused on classical garden design.",
                Decimal("40.00"),
                "09:00-16:30",
            ),
            (
                "Shanghai Museum Stop",
                "museum",
                "A mock overview of art and regional history.",
                Decimal("0.00"),
                "10:00-18:00",
            ),
        ),
    }
)


def search_attractions(requirements: TripRequirements) -> list[Attraction]:
    """Return repeatable attractions for the requested destination."""

    validate_trip_route(requirements, "search_attractions")
    templates = _CITY_ATTRACTIONS.get(requirements.destination.casefold())
    if templates is None:
        templates = _generic_templates(requirements.destination)

    return [
        Attraction(
            name=name,
            city=requirements.destination,
            category=category,
            description=description,
            estimated_cost=mock_amount(requirements.currency, cny_cost),
            currency=requirements.currency,
            opening_hours=opening_hours,
        )
        for name, category, description, cny_cost, opening_hours in templates
    ]


def _generic_templates(city: str) -> tuple[AttractionTemplate, ...]:
    """Build stable fallback attractions for any nonblank destination."""

    city_code = stable_code(city)
    admission = Decimal(20 + city_code % 81)
    return (
        (
            f"{city} Historic Center Walk",
            "culture",
            f"A mock walking introduction to {city}.",
            Decimal("0.00"),
            "Open all day",
        ),
        (
            f"{city} City Museum",
            "museum",
            f"A mock museum visit covering the history of {city}.",
            admission,
            "10:00-17:00",
        ),
        (
            f"{city} Riverside Park",
            "park",
            f"A mock outdoor break in {city}.",
            Decimal("0.00"),
            "06:00-21:00",
        ),
    )
