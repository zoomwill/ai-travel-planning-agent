"""Small official-schema-shaped Duffel fixtures with no real credentials."""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import SecretStr

from app.domain.models import Currency, TripRequirements
from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient, Sleep


def requirements(*, travelers: int = 1, currency: Currency = Currency.USD) -> TripRequirements:
    """Return a future one-way trip that remains inside Duffel's date window."""

    start = date.today() + timedelta(days=30)
    return TripRequirements(
        origin="Cleveland",
        destination="Tokyo",
        start_date=start,
        end_date=start + timedelta(days=2),
        budget=Decimal("5000.00"),
        currency=currency,
        travelers=travelers,
        preferences=["museums"],
    )


def place(
    name: str,
    code: str,
    *,
    latitude: float,
    longitude: float,
    place_type: str = "city",
) -> dict[str, Any]:
    """Build one Places suggestion."""

    return {
        "id": f"plc_{code.lower()}",
        "type": place_type,
        "name": name,
        "iata_code": code,
        "iata_country_code": "US" if code == "CLE" else "JP",
        "latitude": latitude,
        "longitude": longitude,
        "city_name": name,
        "airports": None,
        "time_zone": None,
        "unused_provider_field": {"future": True},
    }


def segment(
    *,
    number: str = "101",
    origin: str = "CLE",
    destination: str = "NRT",
    departing_at: str = "2026-09-27T08:00:00Z",
    arriving_at: str = "2026-09-27T20:00:00Z",
    duration: str | None = "PT12H",
    origin_time_zone: str | None = None,
    destination_time_zone: str | None = None,
) -> dict[str, Any]:
    """Build one provider-shaped operating flight segment."""

    time_zones = {
        "CLE": "America/New_York",
        "ORD": "America/Chicago",
        "NRT": "Asia/Tokyo",
        "LAX": "America/Los_Angeles",
    }
    operating_carrier = {
        "id": "arl_duffel_airways",
        "name": "Duffel Airways",
        "iata_code": "ZZ",
        "logo_symbol_url": "https://assets.duffel.example/symbol.svg",
    }

    return {
        "id": f"seg_{number}",
        "aircraft": {"id": "arc_test", "name": "Test aircraft", "iata_code": "320"},
        "operating_carrier": operating_carrier,
        "operating_carrier_flight_number": number,
        "marketing_carrier": {
            **operating_carrier,
            "logo_lockup_url": "https://assets.duffel.example/lockup.svg",
        },
        "marketing_carrier_flight_number": number,
        "origin": {
            "id": f"arp_{origin.lower()}",
            "type": "airport",
            "name": f"{origin} Airport",
            "iata_code": origin,
            "time_zone": origin_time_zone or time_zones.get(origin),
        },
        "destination": {
            "id": f"arp_{destination.lower()}",
            "type": "airport",
            "name": f"{destination} Airport",
            "iata_code": destination,
            "time_zone": destination_time_zone or time_zones.get(destination),
        },
        "departing_at": departing_at,
        "arriving_at": arriving_at,
        "duration": duration,
        "origin_terminal": None,
        "destination_terminal": "1",
        "distance": None,
        "passengers": [],
        "stops": [],
    }


def offer(
    *,
    offer_id: str = "off_unit",
    segments: list[dict[str, Any]] | None = None,
    duration: str | None = "PT12H",
) -> dict[str, Any]:
    """Build one provider-shaped embedded Flight Offer."""

    values = segments or [segment()]
    return {
        "id": offer_id,
        "total_amount": "1200.50",
        "total_currency": "USD",
        "expires_at": "2026-09-01T00:00:00Z",
        "slices": [
            {
                "id": "sli_unit",
                "origin": values[0]["origin"],
                "destination": values[-1]["destination"],
                "duration": duration,
                "segments": values,
            }
        ],
        "owner": {"id": "arl_owner", "name": "Duffel Airways", "iata_code": "ZZ"},
        "live_mode": False,
        "tax_amount": None,
        "tax_currency": None,
        "unused_provider_field": ["safe", "to", "ignore"],
    }


def stay_result(
    *,
    result_id: str = "srr_unit",
    rating: float | None = None,
    review_score: float | None = None,
    amenities: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build one Stays cheapest-rate result."""

    return {
        "id": result_id,
        "cheapest_rate_total_amount": "600.00",
        "cheapest_rate_currency": "USD",
        "accommodation": {
            "id": "acc_unit",
            "name": "Duffel Test Hotel",
            "rating": rating,
            "review_score": review_score,
            "amenities": amenities,
            "location": {
                "geographic_coordinates": {
                    "latitude": 35.68,
                    "longitude": 139.76,
                }
            },
        },
    }


def make_client(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
    *,
    max_retries: int = 1,
    sleep: Sleep | None = None,
) -> DuffelClient:
    """Create a fixed-host Duffel client backed only by MockTransport."""

    http_client = httpx.AsyncClient(
        base_url=DUFFEL_API_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    kwargs: dict[str, Any] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return DuffelClient(
        http_client,
        access_token=SecretStr("unit-only-token"),
        environment="test",
        api_version="v2",
        timeout_seconds=20,
        max_retries=max_retries,
        **kwargs,
    )
