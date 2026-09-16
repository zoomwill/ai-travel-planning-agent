"""Tests for deterministic Phase P03 mock providers."""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.models import (
    Attraction,
    Currency,
    FlightOption,
    HotelOption,
    TripRequirements,
    WeatherSummary,
)
from app.services.mock_providers import (
    MockProviderInputError,
    get_route,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
)
from app.services.mock_providers.route_provider import RouteUnavailableError


def make_requirements(
    destination: str = "Tokyo",
    currency: Currency = Currency.CNY,
) -> TripRequirements:
    """Build valid requirements for provider tests."""

    return TripRequirements(
        origin="Shanghai",
        destination=destination,
        start_date=date(2027, 4, 10),
        end_date=date(2027, 4, 13),
        budget=Decimal("12000.00"),
        currency=currency,
        travelers=2,
        preferences=["local food", "museums"],
    )


def test_same_input_always_returns_identical_results() -> None:
    requirements = make_requirements()

    assert search_flights(requirements) == search_flights(requirements)
    assert search_hotels(requirements) == search_hotels(requirements)
    assert search_attractions(requirements) == search_attractions(requirements)
    assert get_weather(requirements) == get_weather(requirements)
    for _ in range(2):
        with pytest.raises(RouteUnavailableError):
            get_route("Tokyo Station", "Asakusa")


def test_every_provider_returns_the_declared_model_type() -> None:
    requirements = make_requirements()

    assert all(isinstance(option, FlightOption) for option in search_flights(requirements))
    assert all(isinstance(option, HotelOption) for option in search_hotels(requirements))
    assert all(isinstance(item, Attraction) for item in search_attractions(requirements))
    assert all(isinstance(day, WeatherSummary) for day in get_weather(requirements))
    with pytest.raises(RouteUnavailableError):
        get_route("Tokyo Station", "Asakusa")


def test_every_mock_result_can_be_validated_again() -> None:
    requirements = make_requirements()
    results = [
        *search_flights(requirements),
        *search_hotels(requirements),
        *search_attractions(requirements),
        *get_weather(requirements),
    ]

    for result in results:
        assert type(result).model_validate(result.model_dump()) == result


def test_tokyo_example_is_reasonable_and_matches_source_intent() -> None:
    requirements = make_requirements()
    flights = search_flights(requirements)
    hotels = search_hotels(requirements)
    attractions = search_attractions(requirements)

    assert flights[0].origin == "Shanghai"
    assert flights[0].destination == "Tokyo"
    assert flights[0].price == Decimal("1800.00")
    assert hotels[0].name == "Tokyo Central Hotel"
    assert hotels[0].rating == 4.5
    assert {item.name for item in attractions} >= {
        "Asakusa Heritage Walk",
        "Shinjuku Observation Deck",
    }


def test_different_cities_return_meaningfully_different_results() -> None:
    tokyo = make_requirements("Tokyo")
    paris = make_requirements("Paris")

    assert search_flights(tokyo) != search_flights(paris)
    assert search_hotels(tokyo) != search_hotels(paris)
    assert search_attractions(tokyo) != search_attractions(paris)
    assert get_weather(tokyo) != get_weather(paris)


def test_weather_covers_every_trip_date() -> None:
    weather = get_weather(make_requirements())

    assert [summary.date for summary in weather] == [
        date(2027, 4, 10),
        date(2027, 4, 11),
        date(2027, 4, 12),
        date(2027, 4, 13),
    ]


def test_provider_prices_use_the_requested_currency() -> None:
    requirements = make_requirements(currency=Currency.USD)

    assert all(option.currency is Currency.USD for option in search_flights(requirements))
    assert all(option.currency is Currency.USD for option in search_hotels(requirements))
    assert all(item.currency is Currency.USD for item in search_attractions(requirements))


@pytest.mark.parametrize(
    "provider",
    [search_flights, search_hotels, search_attractions, get_weather],
)
def test_requirement_providers_reject_identical_origin_and_destination(provider: object) -> None:
    requirements = make_requirements(destination="Shanghai")

    with pytest.raises(MockProviderInputError, match="must be different"):
        provider(requirements)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("origin", "destination", "message"),
    [
        ("", "Asakusa", "cannot be blank"),
        ("Tokyo Station", " ", "cannot be blank"),
        ("Asakusa", "asakusa", "must be different"),
    ],
)
def test_route_provider_rejects_invalid_places(
    origin: str,
    destination: str,
    message: str,
) -> None:
    with pytest.raises(MockProviderInputError, match=message):
        get_route(origin, destination)
