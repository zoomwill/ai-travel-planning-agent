"""Lifespan ownership for the multi-provider bundle."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.domain.models import FlightOption, HotelOption, TripRequirements
from app.external.backend import TravelProviderBundle, configured_sources
from app.external.duffel.locations import DuffelLocationResolver
from app.external.duffel.runtime import DuffelRuntime, create_duffel_runtime
from app.external.liteapi.client import LITEAPI_BASE_URL, LiteAPIClient
from app.external.liteapi.hotels import LiteAPIHotelProvider
from app.observability.metrics import MetricsRuntime
from app.search.backend import DeterministicMockSearchBackend
from app.search.models import SearchKind


@dataclass(slots=True)
class TravelProviderRuntime:
    """One app/process owns both pools and closes them even if one cleanup fails."""

    backend: TravelProviderBundle
    duffel: DuffelRuntime | None = None
    liteapi: LiteAPIClient | None = None

    def set_metrics(self, metrics: MetricsRuntime) -> None:
        """Attach the application's isolated metrics registry."""
        if self.duffel is not None:
            self.duffel.client.metrics = metrics
        if self.liteapi is not None:
            self.liteapi.metrics = metrics

    async def aclose(self) -> None:
        """Close both pools on shutdown or cancellation."""
        try:
            if self.liteapi is not None:
                await self.liteapi.aclose()
        finally:
            if self.duffel is not None:
                await self.duffel.aclose()


def create_travel_runtime(
    settings: Settings,
    *,
    duffel_http: httpx.AsyncClient | None = None,
    liteapi_http: httpx.AsyncClient | None = None,
    metrics: MetricsRuntime | None = None,
) -> TravelProviderRuntime:
    """Build selected providers without sending searches or receiving secrets via tools."""

    demo = DeterministicMockSearchBackend()
    if liteapi_http is not None and str(liteapi_http.base_url).rstrip("/") != LITEAPI_BASE_URL:
        raise ValueError("LiteAPI client requires the fixed official host")
    sources = configured_sources(settings)
    duffel = (
        create_duffel_runtime(settings, http_client=duffel_http, metrics=metrics)
        if settings.needs_duffel
        else None
    )
    flight: Callable[[TripRequirements], Awaitable[list[FlightOption]]] = demo.search_flights
    hotel: Callable[[TripRequirements], Awaitable[list[HotelOption]]] = demo.search_hotels
    liteapi = None
    if duffel is not None:
        if settings.selected_flight_provider == "duffel":
            flight = duffel.backend.flights.search
        if settings.selected_hotel_provider == "duffel_stays":
            hotel = duffel.backend.stays.search
        elif settings.selected_hotel_provider == "liteapi":
            liteapi = LiteAPIClient(
                liteapi_http or httpx.AsyncClient(base_url=LITEAPI_BASE_URL),
                api_key=settings.liteapi_api_key,
                environment=settings.liteapi_env,
                timeout_seconds=settings.liteapi_timeout_seconds,
                max_retries=settings.liteapi_max_retries,
                metrics=metrics,
            )
            hotel = LiteAPIHotelProvider(
                liteapi,
                DuffelLocationResolver(duffel.client, require_coordinates=False),
                max_hotels=settings.liteapi_max_hotels,
                max_rates_per_hotel=settings.liteapi_max_rates_per_hotel,
                source=sources[SearchKind.HOTELS],
            ).search
    return TravelProviderRuntime(
        backend=TravelProviderBundle(
            flight,
            hotel,
            sources,
            settings.duffel_allow_demo_fallback,
            settings.liteapi_allow_demo_fallback
            if settings.requires_guest_nationality
            else settings.duffel_allow_demo_fallback,
            flight_limit=settings.duffel_max_flight_offers,
            hotel_limit=settings.liteapi_max_hotels
            if settings.requires_guest_nationality
            else settings.duffel_max_stay_results,
        ),
        duffel=duffel,
        liteapi=liteapi,
    )
