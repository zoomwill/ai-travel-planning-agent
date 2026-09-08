"""One explicitly gated hotel-rates smoke; never print raw responses or credentials."""

import asyncio
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.models import Currency, HotelOption, TravelDataSource, TripRequirements
from app.external.duffel.locations import ResolvedLocation
from app.external.liteapi.client import LITEAPI_BASE_URL, LiteAPIClient
from app.external.liteapi.errors import LiteAPIError, LiteAPISchemaError
from app.external.liteapi.hotels import hotel_request, map_hotels
from app.external.liteapi.models import HotelRatesResponse
from app.external.liteapi.validation import validate_liteapi_response


async def run() -> int:
    """Make at most one HTTP request using an explicit NYC/US sandbox test fixture."""

    if os.environ.get("RUN_LITEAPI_INTEGRATION_TESTS") != "1":
        print("FAIL LiteAPI gate: explicitly set RUN_LITEAPI_INTEGRATION_TESTS=1")
        return 1
    try:
        settings = Settings()
    except ValidationError:
        print("FAIL LiteAPI configuration: invalid settings (values hidden)")
        return 1
    if not settings.liteapi_is_configured:
        print("FAIL LiteAPI configuration: liteapi_not_configured")
        return 1
    if settings.liteapi_env != "sandbox":
        print("FAIL LiteAPI environment: this acceptance checker requires sandbox")
        return 1
    print("PASS LiteAPI environment: sandbox")
    center = ResolvedLocation(
        "New York test search", "US", "New York", "NYC", ("NYC",), 40.7128, -74.0060
    )
    checkin = date.today() + timedelta(days=30)
    trip = TripRequirements(
        origin="London",
        destination="New York",
        start_date=checkin,
        end_date=checkin + timedelta(days=1),
        budget=Decimal("10000"),
        currency=Currency.USD,
        travelers=1,
        guest_nationality="US",
    )  # Explicit smoke fixture, never planner default.
    client = LiteAPIClient(
        httpx.AsyncClient(base_url=LITEAPI_BASE_URL),
        api_key=settings.liteapi_api_key,
        environment=settings.liteapi_env,
        timeout_seconds=settings.liteapi_timeout_seconds,
        max_retries=0,
    )
    try:
        body = hotel_request(
            trip, center, max_hotels=min(5, settings.liteapi_max_hotels), max_rates_per_hotel=1
        )
        response = validate_liteapi_response(HotelRatesResponse, await client.hotel_rates(body))
        if response.sandbox is False:
            raise LiteAPIError("liteapi_invalid_response")
        hotels = map_hotels(
            response,
            trip,
            center,
            max_hotels=min(5, settings.liteapi_max_hotels),
            source=TravelDataSource.LITEAPI_SANDBOX,
        )
        if not hotels or any(
            HotelOption.model_validate(hotel.model_dump()).data_source
            is not TravelDataSource.LITEAPI_SANDBOX
            for hotel in hotels
        ):
            raise LiteAPIError("liteapi_invalid_response")
        print("PASS Hotel rates access")
        print(f"PASS Hotels returned: {len(response.data)}")
        print(f"PASS Mapped hotel candidates: {len(hotels)}")
        print("PASS Hotel domain/source: liteapi_sandbox")
        return 0
    except LiteAPISchemaError as exc:
        print(f"FAIL LiteAPI response: {exc.code}")
        print(
            f"INFO provider=liteapi operation=hotel_rates validation_error_count={exc.error_count}"
        )
        for issue in exc.issues:
            print(f"INFO loc={issue.loc} type={issue.type}")
        return 1
    except LiteAPIError as exc:
        print(f"FAIL Hotel rates: {exc.code}")
        return 1
    except Exception:
        print("FAIL LiteAPI smoke: unexpected local failure (details hidden)")
        return 1
    finally:
        await client.aclose()


def main() -> int:
    """Enter the asynchronous, non-retrying checker."""
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
