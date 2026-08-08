"""Deterministic local substitutes for future external travel providers."""

from app.services.mock_providers.attraction_provider import search_attractions
from app.services.mock_providers.exceptions import MockProviderInputError
from app.services.mock_providers.flight_provider import search_flights
from app.services.mock_providers.hotel_provider import search_hotels
from app.services.mock_providers.route_provider import get_route
from app.services.mock_providers.weather_provider import get_weather

__all__ = [
    "MockProviderInputError",
    "get_route",
    "get_weather",
    "search_attractions",
    "search_flights",
    "search_hotels",
]
