"""Injectable asynchronous adapters for deterministic travel searches."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TripRequirements,
    WeatherSummary,
)
from app.services.mock_providers import (
    get_route,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
)

FlightProvider = Callable[[TripRequirements], list[FlightOption]]
HotelProvider = Callable[[TripRequirements], list[HotelOption]]
AttractionProvider = Callable[[TripRequirements], list[Attraction]]
WeatherProvider = Callable[[TripRequirements], list[WeatherSummary]]
RouteProvider = Callable[[str, str], RouteSummary]


class SearchBackend(Protocol):
    """Asynchronous boundary used by the five LangGraph search subagents."""

    async def search_flights(
        self,
        requirements: TripRequirements,
    ) -> list[FlightOption]:
        """Return available deterministic flight options."""

    async def search_hotels(
        self,
        requirements: TripRequirements,
    ) -> list[HotelOption]:
        """Return available deterministic hotel options."""

    async def search_attractions(
        self,
        requirements: TripRequirements,
    ) -> list[Attraction]:
        """Return deterministic destination attractions."""

    async def get_weather(
        self,
        requirements: TripRequirements,
    ) -> list[WeatherSummary]:
        """Return deterministic weather for every trip date."""

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Return one deterministic origin-to-destination route."""


@dataclass(frozen=True, slots=True)
class DeterministicMockSearchBackend:
    """Adapt the existing synchronous mock providers without changing their output."""

    flight_provider: FlightProvider = search_flights
    hotel_provider: HotelProvider = search_hotels
    attraction_provider: AttractionProvider = search_attractions
    weather_provider: WeatherProvider = get_weather
    route_provider: RouteProvider = get_route

    async def search_flights(
        self,
        requirements: TripRequirements,
    ) -> list[FlightOption]:
        """Run only the flight provider outside the event-loop thread."""

        return await asyncio.to_thread(self.flight_provider, requirements)

    async def search_hotels(
        self,
        requirements: TripRequirements,
    ) -> list[HotelOption]:
        """Run only the hotel provider outside the event-loop thread."""

        return await asyncio.to_thread(self.hotel_provider, requirements)

    async def search_attractions(
        self,
        requirements: TripRequirements,
    ) -> list[Attraction]:
        """Run only the attraction provider outside the event-loop thread."""

        return await asyncio.to_thread(self.attraction_provider, requirements)

    async def get_weather(
        self,
        requirements: TripRequirements,
    ) -> list[WeatherSummary]:
        """Run only the weather provider outside the event-loop thread."""

        return await asyncio.to_thread(self.weather_provider, requirements)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Run only the route provider outside the event-loop thread."""

        return await asyncio.to_thread(self.route_provider, origin, destination)
