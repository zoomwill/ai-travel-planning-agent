"""Low-cardinality P17 external-request and travel-source metrics."""

import httpx
import pytest
from prometheus_client import generate_latest
from pydantic import SecretStr

from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient
from app.observability.instrumentation import InstrumentedSearchBackend
from app.observability.metrics import MetricsRuntime
from app.search.backend import DeterministicMockSearchBackend
from tests.external.duffel.helpers import requirements


@pytest.mark.asyncio
async def test_external_metrics_use_only_bounded_labels() -> None:
    metrics = MetricsRuntime.create()
    http_client = httpx.AsyncClient(
        base_url=DUFFEL_API_BASE_URL,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []})),
    )
    client = DuffelClient(
        http_client,
        access_token=SecretStr("unit-only-token"),
        environment="test",
        api_version="v2",
        timeout_seconds=20,
        max_retries=0,
        metrics=metrics,
    )
    await client.get("/places/suggestions", params={"query": "Tokyo"}, operation="location_lookup")
    await client.aclose()

    exposition = generate_latest(metrics.registry).decode()
    assert 'provider="duffel",status="success"' in exposition
    assert 'operation="location_lookup"' in exposition
    assert "Tokyo" not in exposition
    assert "unit-only-token" not in exposition


@pytest.mark.asyncio
async def test_search_source_metric_records_demo_without_city_label() -> None:
    metrics = MetricsRuntime.create()
    backend = InstrumentedSearchBackend(DeterministicMockSearchBackend(), metrics, "direct")
    await backend.search_flights(requirements())

    exposition = generate_latest(metrics.registry).decode()
    assert 'kind="flights",source="demo",status="success"' in exposition
    assert "Cleveland" not in exposition
