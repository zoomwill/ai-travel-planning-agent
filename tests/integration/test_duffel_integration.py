"""Explicitly gated real Duffel test-mode transport checks."""

import os
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.domain.models import Currency, TravelDataSource, TripRequirements
from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import DuffelLocationResolver, ResolvedLocation
from app.external.duffel.mapper import map_flight_offer, map_stay_result
from app.external.duffel.models import OfferRequestResponse, StaySearchResponse

pytestmark = pytest.mark.duffel_integration


def _token() -> str:
    if os.environ.get("RUN_DUFFEL_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_DUFFEL_INTEGRATION_TESTS=1 for real Duffel tests")
    token = Settings().duffel_access_token.get_secret_value()
    if not token:
        pytest.skip("DUFFEL_ACCESS_TOKEN is not configured")
    if not token.startswith("duffel_test_"):
        pytest.skip("P17 real acceptance only permits a Duffel test-mode token")
    return token


def _client(token: str) -> DuffelClient:
    return DuffelClient(
        httpx.AsyncClient(base_url=DUFFEL_API_BASE_URL),
        access_token=SecretStr(token),
        environment="test",
        api_version="v2",
        timeout_seconds=20,
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_real_duffel_flights() -> None:
    """Use Duffel's documented LHR-DXB connecting-flight test scenario."""

    client = _client(_token())
    departure = date.today() + timedelta(days=30)
    try:
        origin = await DuffelLocationResolver(client).resolve("LHR")
        destination = await DuffelLocationResolver(client).resolve("DXB")
        payload = await client.post(
            "/air/offer_requests",
            operation="flight_offer_request",
            json={
                "data": {
                    "slices": [
                        {
                            "origin": origin.iata_code,
                            "destination": destination.iata_code,
                            "departure_date": departure.isoformat(),
                        }
                    ],
                    "passengers": [{"type": "adult"}],
                    "cabin_class": "economy",
                }
            },
        )
        response = OfferRequestResponse.model_validate(payload)
        assert response.data.offers
        currency = Currency(response.data.offers[0].total_currency)
        requirements = TripRequirements(
            origin="London",
            destination="Dubai",
            start_date=departure,
            end_date=departure,
            budget=Decimal("100000"),
            currency=currency,
            travelers=1,
        )
        mapped = map_flight_offer(
            response.data.offers[0],
            requirements,
            TravelDataSource.DUFFEL_TEST,
        )
        assert mapped.segments
        assert mapped.provider_offer_id
    except ValidationError as exc:
        pytest.fail(f"Duffel returned an unsupported response shape: {type(exc).__name__}")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_real_duffel_stays() -> None:
    """Use Duffel's documented test-hotel coordinates when Stays access exists."""

    client = _client(_token())
    check_in = date.today() + timedelta(days=30)
    center = ResolvedLocation(
        name="Duffel test hotels",
        country_code="PN",
        city="Duffel test hotels",
        iata_code="AAA",
        iata_codes=("AAA",),
        latitude=-24.38,
        longitude=-128.32,
    )
    try:
        try:
            payload = await client.post(
                "/stays/search",
                operation="stay_search",
                json={
                    "data": {
                        "location": {
                            "radius": 2,
                            "geographic_coordinates": {
                                "latitude": center.latitude,
                                "longitude": center.longitude,
                            },
                        },
                        "check_in_date": check_in.isoformat(),
                        "check_out_date": (check_in + timedelta(days=1)).isoformat(),
                        "guests": [{"type": "adult"}],
                        "rooms": 1,
                    }
                },
            )
        except DuffelError as exc:
            if exc.code == "duffel_stays_access_denied":
                pytest.skip("Duffel Stays access is not enabled for this account")
            raise
        response = StaySearchResponse.model_validate(payload)
        assert response.data.results
        currency = Currency(response.data.results[0].cheapest_rate_currency)
        requirements = TripRequirements(
            origin="London",
            destination="Duffel test hotels",
            start_date=check_in,
            end_date=check_in,
            budget=Decimal("100000"),
            currency=currency,
            travelers=1,
        )
        mapped = map_stay_result(
            response.data.results[0],
            requirements,
            center,
            1,
            TravelDataSource.DUFFEL_TEST,
        )
        assert mapped.provider_hotel_id
        assert mapped.price_per_night > 0
    except ValidationError as exc:
        pytest.fail(f"Duffel returned an unsupported response shape: {type(exc).__name__}")
    finally:
        await client.aclose()
