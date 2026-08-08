"""Private deterministic helpers shared by mock providers."""

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.domain.models import Currency, TripRequirements
from app.services.mock_providers.exceptions import MockProviderInputError

_CURRENCY_FACTORS: Final[Mapping[Currency, Decimal]] = MappingProxyType(
    {
        Currency.CNY: Decimal("1.00"),
        Currency.USD: Decimal("0.14"),
        Currency.JPY: Decimal("20.00"),
        Currency.EUR: Decimal("0.13"),
    }
)


def stable_code(*parts: str) -> int:
    """Return a process-independent integer derived only from input text."""

    normalized = "|".join(part.strip().casefold() for part in parts)
    return sum((index + 1) * ord(character) for index, character in enumerate(normalized))


def mock_amount(currency: Currency, cny_amount: Decimal) -> Decimal:
    """Scale a CNY-denominated mock amount using fixed non-market factors."""

    return (cny_amount * _CURRENCY_FACTORS[currency]).quantize(Decimal("0.01"))


def require_distinct_places(origin: str, destination: str, provider: str) -> None:
    """Reject blank or identical route endpoints."""

    normalized_origin = origin.strip().casefold()
    normalized_destination = destination.strip().casefold()
    if not normalized_origin or not normalized_destination:
        raise MockProviderInputError(provider, "origin and destination cannot be blank")
    if normalized_origin == normalized_destination:
        raise MockProviderInputError(provider, "origin and destination must be different")


def validate_trip_route(requirements: TripRequirements, provider: str) -> None:
    """Validate route fields shared by requirement-based providers."""

    require_distinct_places(requirements.origin, requirements.destination, provider)
