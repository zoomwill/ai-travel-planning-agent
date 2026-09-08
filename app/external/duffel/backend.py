"""Travel SearchBackend bundle for Duffel plus explicitly labeled demo searches."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TravelDataSource,
    TripRequirements,
    WeatherSummary,
)
from app.external.duffel.errors import DuffelError
from app.external.duffel.flights import DuffelFlightProvider
from app.external.duffel.stays import DuffelStayProvider
from app.observability.logging import log_event
from app.search.backend import DeterministicMockSearchBackend
from app.search.models import SearchKind

ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class DuffelTravelSearchBackend:
    """Use Duffel only for flights/stays and keep the other three searches demo."""

    flights: DuffelFlightProvider
    stays: DuffelStayProvider
    source: TravelDataSource
    allow_demo_fallback: bool = False
    demo: DeterministicMockSearchBackend = DeterministicMockSearchBackend()

    def source_for(self, kind: SearchKind) -> TravelDataSource:
        """Return the configured source before a branch has produced output."""

        if kind in {SearchKind.FLIGHTS, SearchKind.HOTELS}:
            return self.source
        return TravelDataSource.DEMO

    async def search_flights(self, requirements: TripRequirements) -> list[FlightOption]:
        """Search Duffel Flights, optionally using an explicit labeled fallback."""

        return await self._external_or_fallback(
            SearchKind.FLIGHTS,
            lambda: self.flights.search(requirements),
            lambda: self.demo.search_flights(requirements),
        )

    async def search_hotels(self, requirements: TripRequirements) -> list[HotelOption]:
        """Search Duffel Stays, optionally using an explicit labeled fallback."""

        return await self._external_or_fallback(
            SearchKind.HOTELS,
            lambda: self.stays.search(requirements),
            lambda: self.demo.search_hotels(requirements),
        )

    async def search_attractions(self, requirements: TripRequirements) -> list[Attraction]:
        """Keep attractions on deterministic demo data in P17."""

        return await self.demo.search_attractions(requirements)

    async def get_weather(self, requirements: TripRequirements) -> list[WeatherSummary]:
        """Keep weather on deterministic demo data in P17."""

        return await self.demo.get_weather(requirements)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Keep route estimates on deterministic demo data in P17."""

        return await self.demo.get_route(origin, destination)

    async def _external_or_fallback(
        self,
        kind: SearchKind,
        external: Callable[[], Awaitable[list[ResultT]]],
        fallback: Callable[[], Awaitable[list[ResultT]]],
    ) -> list[ResultT]:
        try:
            return await external()
        except DuffelError as exc:
            if not self.allow_demo_fallback:
                raise
            log_event(
                "external_demo_fallback",
                "An explicitly enabled demo fallback replaced external travel data.",
                component="external",
                provider="duffel",
                operation=kind.value,
                environment=self.source.value,
                outcome="fallback",
                error_code=exc.code,
            )
            results = await fallback()
            return [
                result.model_copy(update={"data_source": TravelDataSource.DEMO_FALLBACK})
                for result in results
            ]
