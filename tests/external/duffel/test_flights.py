"""Offline Flight Offer Request and multi-segment mapping tests."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.domain.models import TravelDataSource
from app.external.duffel.errors import DuffelError
from app.external.duffel.flights import DuffelFlightProvider
from app.external.duffel.locations import ResolvedLocation
from app.llm.grounding import stable_candidate_id
from tests.external.duffel.helpers import make_client, offer, requirements, segment


class Resolver:
    """Return authoritative test locations without adding HTTP calls."""

    async def resolve(self, query: str) -> ResolvedLocation:
        code = "CLE" if query == "Cleveland" else "TYO"
        return ResolvedLocation(query, "US", query, code, (code,), 35.0, 139.0)


@pytest.mark.asyncio
async def test_one_way_offer_request_passengers_limit_and_mapping() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"offers": [offer(), offer(offer_id="off_2")]}})

    trip = requirements(travelers=2)
    client = make_client(handler)
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=1,
        source=TravelDataSource.DUFFEL_TEST,
    )
    results = await provider.search(trip)
    await client.aclose()

    body = __import__("json").loads(requests[0].content)
    assert requests[0].url.path == "/air/offer_requests"
    assert dict(requests[0].url.params) == {"return_offers": "true", "view": "offers"}
    assert body["data"]["slices"] == [
        {"origin": "CLE", "destination": "TYO", "departure_date": trip.start_date.isoformat()}
    ]
    assert body["data"]["passengers"] == [{"type": "adult"}, {"type": "adult"}]
    assert len(results) == 1
    assert results[0].price == Decimal("1200.50")
    assert results[0].provider_offer_id == "off_unit"
    assert results[0].data_source is TravelDataSource.DUFFEL_TEST


@pytest.mark.asyncio
async def test_connecting_offer_preserves_all_segments_and_stops() -> None:
    segments = [
        segment(
            number="101",
            origin="CLE",
            destination="ORD",
            arriving_at="2026-09-27T10:00:00Z",
            duration="PT2H",
        ),
        segment(
            number="202",
            origin="ORD",
            destination="NRT",
            departing_at="2026-09-27T12:00:00Z",
            arriving_at="2026-09-28T00:00:00Z",
            duration="PT12H",
        ),
    ]
    value = offer(segments=segments)
    value["slices"][0]["duration"] = "PT16H"
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": [value]}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()

    assert result.stops == 1
    assert [item.flight_number for item in result.segments] == ["ZZ101", "ZZ202"]
    assert [item.origin_iata_code for item in result.segments] == ["CLE", "ORD"]
    assert result.duration_minutes == 960
    assert result.arrival_time == datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_nullable_durations_use_airport_time_zones_without_losing_segments() -> None:
    value = offer(
        duration=None,
        segments=[
            segment(
                number="0007",
                origin="NRT",
                destination="LAX",
                departing_at="2026-09-27T17:00:00",
                arriving_at="2026-09-27T10:00:00",
                duration=None,
            )
        ],
    )
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": [value]}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()

    assert result.duration_minutes == 540
    assert result.segments[0].duration_minutes == 540
    assert result.segments[0].flight_number == "ZZ0007"
    assert result.segments[0].airline == "Duffel Airways"
    assert result.stops == 0


@pytest.mark.asyncio
async def test_iso_day_duration_and_missing_operating_number_use_marketing_identity() -> None:
    flight_segment = segment(
        number="9999",
        departing_at="2026-09-27T08:00:00Z",
        arriving_at="2026-09-28T10:00:00Z",
        duration="P1DT2H",
    )
    flight_segment["operating_carrier_flight_number"] = None
    flight_segment["marketing_carrier"] = {
        "id": "arl_marketing",
        "name": "Marketing Airways",
        "iata_code": "MK",
    }
    flight_segment["marketing_carrier_flight_number"] = "007"
    value = offer(duration="P1DT2H", segments=[flight_segment])
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": [value]}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()

    assert result.duration_minutes == 1560
    assert result.segments[0].duration_minutes == 1560
    assert result.segments[0].flight_number == "MK007"
    assert result.segments[0].airline == "Duffel Airways"


@pytest.mark.asyncio
async def test_no_offers_and_malformed_segment_are_safe_errors() -> None:
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": []}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    with pytest.raises(DuffelError, match="duffel_no_flight_offers"):
        await provider.search(requirements())
    await client.aclose()

    malformed = offer()
    del malformed["slices"][0]["segments"][0]["origin"]
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": [malformed]}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    with pytest.raises(DuffelError, match="duffel_invalid_response"):
        await provider.search(requirements())
    await client.aclose()


@pytest.mark.asyncio
async def test_candidate_identity_excludes_offer_id_expiry_and_source() -> None:
    client = make_client(lambda _: httpx.Response(200, json={"data": {"offers": [offer()]}}))
    provider = DuffelFlightProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_offers=5,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()
    changed = result.model_copy(
        update={
            "provider_offer_id": "off_changed",
            "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
            "data_source": TravelDataSource.DUFFEL_LIVE,
        }
    )

    assert stable_candidate_id("flight", result) == stable_candidate_id("flight", changed)
