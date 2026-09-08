"""Creation and ownership of one shared Duffel HTTP runtime."""

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.domain.models import TravelDataSource
from app.external.duffel.backend import DuffelTravelSearchBackend
from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient, Sleep
from app.external.duffel.flights import DuffelFlightProvider
from app.external.duffel.locations import DuffelLocationResolver
from app.external.duffel.stays import DuffelStayProvider
from app.observability.metrics import MetricsRuntime


@dataclass(slots=True)
class DuffelRuntime:
    """Application-owned client and provider bundle with one cleanup method."""

    client: DuffelClient
    backend: DuffelTravelSearchBackend

    async def aclose(self) -> None:
        """Close the shared HTTP connection pool exactly once."""

        await self.client.aclose()


def create_duffel_runtime(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    sleep: Sleep | None = None,
    metrics: MetricsRuntime | None = None,
) -> DuffelRuntime:
    """Build the P17 runtime without sending any remote request."""

    owned_http = http_client or httpx.AsyncClient(base_url=DUFFEL_API_BASE_URL)
    if sleep is None:
        client = DuffelClient(
            owned_http,
            access_token=settings.duffel_access_token,
            environment=settings.duffel_env,
            api_version=settings.duffel_api_version,
            timeout_seconds=settings.duffel_timeout_seconds,
            max_retries=settings.duffel_max_retries,
            metrics=metrics,
        )
    else:
        client = DuffelClient(
            owned_http,
            access_token=settings.duffel_access_token,
            environment=settings.duffel_env,
            api_version=settings.duffel_api_version,
            timeout_seconds=settings.duffel_timeout_seconds,
            max_retries=settings.duffel_max_retries,
            metrics=metrics,
            sleep=sleep,
        )
    resolver = DuffelLocationResolver(client)
    source = (
        TravelDataSource.DUFFEL_TEST
        if settings.duffel_env == "test"
        else TravelDataSource.DUFFEL_LIVE
    )
    backend = DuffelTravelSearchBackend(
        flights=DuffelFlightProvider(
            client,
            resolver,
            max_offers=settings.duffel_max_flight_offers,
            source=source,
        ),
        stays=DuffelStayProvider(
            client,
            resolver,
            max_results=settings.duffel_max_stay_results,
            source=source,
        ),
        source=source,
        allow_demo_fallback=settings.duffel_allow_demo_fallback,
    )
    return DuffelRuntime(client=client, backend=backend)
