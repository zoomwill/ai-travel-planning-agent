"""Tests for the asynchronous adapter over existing P03 mock providers."""

from app.domain.models import Attraction, FlightOption, HotelOption, RouteSummary, WeatherSummary
from app.search.backend import DeterministicMockSearchBackend
from tests.search.test_models import make_requirements


async def test_default_backend_maps_all_five_existing_providers() -> None:
    """Every async method returns the existing provider's typed deterministic data."""

    requirements = make_requirements()
    backend = DeterministicMockSearchBackend()

    flights = await backend.search_flights(requirements)
    hotels = await backend.search_hotels(requirements)
    attractions = await backend.search_attractions(requirements)
    weather = await backend.get_weather(requirements)
    route = await backend.get_route(requirements.origin, requirements.destination)

    assert all(isinstance(item, FlightOption) for item in flights)
    assert all(isinstance(item, HotelOption) for item in hotels)
    assert all(isinstance(item, Attraction) for item in attractions)
    assert all(isinstance(item, WeatherSummary) for item in weather)
    assert isinstance(route, RouteSummary)


async def test_default_backend_remains_deterministic() -> None:
    """Async adaptation does not introduce time, sleep, or random output."""

    requirements = make_requirements()
    backend = DeterministicMockSearchBackend()

    assert await backend.search_flights(requirements) == await backend.search_flights(requirements)
    assert await backend.get_route(
        requirements.origin, requirements.destination
    ) == await backend.get_route(requirements.origin, requirements.destination)
