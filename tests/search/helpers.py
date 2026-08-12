"""Inspectable asynchronous search backends used only by P08 tests."""

import asyncio

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TripRequirements,
    WeatherSummary,
)
from app.search.models import SearchKind
from app.services.mock_providers import (
    get_route,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
)


class RecordingSearchBackend:
    """Return real deterministic mock data while recording each async method call."""

    def __init__(self, fail_kind: SearchKind | None = None) -> None:
        self.fail_kind = fail_kind
        self.calls = {kind: 0 for kind in SearchKind}

    def _record(self, kind: SearchKind) -> None:
        """Record one call and optionally raise a private test exception."""

        self.calls[kind] += 1
        if kind is self.fail_kind:
            raise RuntimeError("private backend detail")

    async def search_flights(
        self,
        requirements: TripRequirements,
    ) -> list[FlightOption]:
        """Record and return deterministic flights."""

        self._record(SearchKind.FLIGHTS)
        return search_flights(requirements)

    async def search_hotels(
        self,
        requirements: TripRequirements,
    ) -> list[HotelOption]:
        """Record and return deterministic hotels."""

        self._record(SearchKind.HOTELS)
        return search_hotels(requirements)

    async def search_attractions(
        self,
        requirements: TripRequirements,
    ) -> list[Attraction]:
        """Record and return deterministic attractions."""

        self._record(SearchKind.ATTRACTIONS)
        return search_attractions(requirements)

    async def get_weather(
        self,
        requirements: TripRequirements,
    ) -> list[WeatherSummary]:
        """Record and return deterministic weather."""

        self._record(SearchKind.WEATHER)
        return get_weather(requirements)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Record and return one deterministic route."""

        self._record(SearchKind.ROUTE)
        return get_route(origin, destination)


class BarrierSearchBackend(RecordingSearchBackend):
    """Wait until all five methods enter before allowing any one to return."""

    def __init__(self) -> None:
        super().__init__()
        self.started: set[SearchKind] = set()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def _wait_at_barrier(self, kind: SearchKind) -> None:
        """Record concurrent entry and block until the test releases all workers."""

        self.started.add(kind)
        if len(self.started) == len(SearchKind):
            self.all_started.set()
        await self.release.wait()

    async def search_flights(
        self,
        requirements: TripRequirements,
    ) -> list[FlightOption]:
        """Wait with the flight branch before returning its mock data."""

        await self._wait_at_barrier(SearchKind.FLIGHTS)
        return await super().search_flights(requirements)

    async def search_hotels(
        self,
        requirements: TripRequirements,
    ) -> list[HotelOption]:
        """Wait with the hotel branch before returning its mock data."""

        await self._wait_at_barrier(SearchKind.HOTELS)
        return await super().search_hotels(requirements)

    async def search_attractions(
        self,
        requirements: TripRequirements,
    ) -> list[Attraction]:
        """Wait with the attraction branch before returning its mock data."""

        await self._wait_at_barrier(SearchKind.ATTRACTIONS)
        return await super().search_attractions(requirements)

    async def get_weather(
        self,
        requirements: TripRequirements,
    ) -> list[WeatherSummary]:
        """Wait with the weather branch before returning its mock data."""

        await self._wait_at_barrier(SearchKind.WEATHER)
        return await super().get_weather(requirements)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Wait with the route branch before returning its mock data."""

        await self._wait_at_barrier(SearchKind.ROUTE)
        return await super().get_route(origin, destination)
