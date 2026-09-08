"""Per-kind provider composition, independent of LangGraph and MCP transport."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import Settings
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
from app.external.liteapi.errors import LiteAPIError
from app.observability.logging import log_event
from app.search.backend import DeterministicMockSearchBackend
from app.search.models import SearchKind

ResultT = TypeVar("ResultT", bound=BaseModel)


def configured_sources(settings: Settings) -> dict[SearchKind, TravelDataSource]:
    """Describe all five selected sources without constructing clients or doing I/O."""

    sources = dict.fromkeys(SearchKind, TravelDataSource.DEMO)
    duffel = (
        TravelDataSource.DUFFEL_TEST
        if settings.duffel_env == "test"
        else TravelDataSource.DUFFEL_LIVE
    )
    if settings.selected_flight_provider == "duffel":
        sources[SearchKind.FLIGHTS] = duffel
    if settings.selected_hotel_provider == "duffel_stays":
        sources[SearchKind.HOTELS] = duffel
    elif settings.selected_hotel_provider == "liteapi":
        sources[SearchKind.HOTELS] = (
            TravelDataSource.LITEAPI_SANDBOX
            if settings.liteapi_env == "sandbox"
            else TravelDataSource.LITEAPI_PRODUCTION
        )
    return sources


@dataclass(frozen=True, slots=True)
class TravelProviderBundle:
    """Keep flight/hotel selection centralized; the other three kinds stay demo."""

    flight_provider: Callable[[TripRequirements], Awaitable[list[FlightOption]]]
    hotel_provider: Callable[[TripRequirements], Awaitable[list[HotelOption]]]
    sources: dict[SearchKind, TravelDataSource]
    flight_fallback: bool = False
    hotel_fallback: bool = False
    demo: DeterministicMockSearchBackend = field(default_factory=DeterministicMockSearchBackend)
    flight_limit: int = 20
    hotel_limit: int = 20

    def source_for(self, kind: SearchKind) -> TravelDataSource:
        """Return expected provenance before a result becomes available."""

        return self.sources[kind]

    async def search_flights(self, requirements: TripRequirements) -> list[FlightOption]:
        """Use only the selected flight provider."""

        results = await self._search(
            self.flight_provider,
            self.demo.search_flights,
            requirements,
            SearchKind.FLIGHTS,
            self.flight_fallback,
        )
        return (
            results
            if self.sources[SearchKind.FLIGHTS] is TravelDataSource.DEMO
            else results[: self.flight_limit]
        )

    async def search_hotels(self, requirements: TripRequirements) -> list[HotelOption]:
        """Use only the selected hotel provider."""

        results = await self._search(
            self.hotel_provider,
            self.demo.search_hotels,
            requirements,
            SearchKind.HOTELS,
            self.hotel_fallback,
        )
        return (
            results
            if self.sources[SearchKind.HOTELS] is TravelDataSource.DEMO
            else results[: self.hotel_limit]
        )

    async def _search(
        self,
        provider: Callable[[TripRequirements], Awaitable[list[ResultT]]],
        demo: Callable[[TripRequirements], Awaitable[list[ResultT]]],
        trip: TripRequirements,
        kind: SearchKind,
        fallback: bool,
    ) -> list[ResultT]:
        try:
            return await provider(trip)
        except (DuffelError, LiteAPIError):
            if not fallback:
                raise
            log_event(
                "external_demo_fallback",
                "Explicit demo fallback used.",
                provider="liteapi" if self.sources[kind].value.startswith("liteapi_") else "duffel",
                operation=kind.value,
                outcome="fallback",
                source="demo_fallback",
            )
            return [
                item.model_copy(update={"data_source": TravelDataSource.DEMO_FALLBACK})
                for item in await demo(trip)
            ]

    async def search_attractions(self, requirements: TripRequirements) -> list[Attraction]:
        """Keep attractions deterministic."""
        return await self.demo.search_attractions(requirements)

    async def get_weather(self, requirements: TripRequirements) -> list[WeatherSummary]:
        """Keep weather deterministic."""
        return await self.demo.get_weather(requirements)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Keep routes deterministic."""
        return await self.demo.get_route(origin, destination)
