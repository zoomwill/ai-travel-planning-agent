"""Offline Stays request, pricing, nullable facts, and access tests."""

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from app.domain.models import TravelDataSource
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import ResolvedLocation
from app.external.duffel.stays import DuffelStayProvider
from app.llm.grounding import stable_candidate_id
from tests.external.duffel.helpers import make_client, requirements, stay_result


class Resolver:
    """Return one provider-backed center used to verify the Stays request."""

    async def resolve(self, query: str) -> ResolvedLocation:
        return ResolvedLocation(query, "JP", query, "TYO", ("TYO",), 35.6762, 139.6503)


@pytest.mark.asyncio
async def test_stay_search_request_and_total_to_nightly_mapping() -> None:
    requests: list[httpx.Request] = []
    values = [stay_result(result_id="srr_1"), stay_result(result_id="srr_2")]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"results": values}})

    trip = requirements(travelers=2)
    client = make_client(handler)
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=1,
        source=TravelDataSource.DUFFEL_TEST,
    )
    results = await provider.search(trip)
    await client.aclose()

    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/stays/search"
    assert body["data"]["rooms"] == 1
    assert body["data"]["guests"] == [{"type": "adult"}, {"type": "adult"}]
    assert body["data"]["check_in_date"] == trip.start_date.isoformat()
    assert body["data"]["check_out_date"] == (trip.end_date + timedelta(days=1)).isoformat()
    assert len(results) == 1
    assert results[0].price_per_night == Decimal("200.00")
    assert results[0].provider_hotel_id == "acc_unit"
    assert results[0].provider_search_result_id == "srr_1"
    assert results[0].distance_to_center_km is not None


@pytest.mark.asyncio
async def test_nullable_rating_review_and_amenities_remain_honest() -> None:
    client = make_client(
        lambda _: httpx.Response(
            200,
            json={"data": {"results": [stay_result(amenities=None)]}},
        )
    )
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=10,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()

    assert result.rating is None
    assert result.review_score is None
    assert result.amenities == []


@pytest.mark.asyncio
async def test_rating_and_review_score_stay_distinct() -> None:
    value = stay_result(
        rating=4,
        review_score=8.8,
        amenities=[{"type": "parking", "description": "Parking"}],
    )
    client = make_client(lambda _: httpx.Response(200, json={"data": {"results": [value]}}))
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=10,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()
    assert (result.rating, result.review_score, result.amenities) == (4, 8.8, ["Parking"])


@pytest.mark.asyncio
async def test_unsupported_party_is_rejected_before_http() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"results": []}})

    client = make_client(handler)
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=10,
        source=TravelDataSource.DUFFEL_TEST,
    )
    with pytest.raises(DuffelError, match="duffel_unsupported_request"):
        await provider.search(requirements(travelers=3))
    await client.aclose()
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, json={"data": {"results": []}}), "duffel_no_stay_results"),
        (httpx.Response(403, json={"errors": []}), "duffel_stays_access_denied"),
        (
            httpx.Response(200, json={"data": {"results": [{"id": "bad"}]}}),
            "duffel_invalid_response",
        ),
    ],
)
async def test_empty_access_denied_and_malformed_results(
    response: httpx.Response,
    expected: str,
) -> None:
    client = make_client(lambda _: response, max_retries=0)
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=10,
        source=TravelDataSource.DUFFEL_TEST,
    )
    with pytest.raises(DuffelError, match=expected):
        await provider.search(requirements())
    await client.aclose()


@pytest.mark.asyncio
async def test_hotel_candidate_identity_ignores_volatile_search_id_and_source() -> None:
    client = make_client(lambda _: httpx.Response(200, json={"data": {"results": [stay_result()]}}))
    provider = DuffelStayProvider(
        client,
        Resolver(),  # type: ignore[arg-type]
        max_results=10,
        source=TravelDataSource.DUFFEL_TEST,
    )
    result = (await provider.search(requirements()))[0]
    await client.aclose()
    changed = result.model_copy(
        update={
            "provider_search_result_id": "srr_changed",
            "data_source": TravelDataSource.DUFFEL_LIVE,
        }
    )
    assert stable_candidate_id("hotel", result) == stable_candidate_id("hotel", changed)
