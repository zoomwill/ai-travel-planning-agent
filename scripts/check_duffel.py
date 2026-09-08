"""Explicit Duffel test-mode Flights and optional Stays smoke checker."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

import httpx

from app.core.config import Settings
from app.external.duffel.client import DUFFEL_API_BASE_URL, DuffelClient
from app.external.duffel.errors import DuffelError, DuffelSchemaError
from app.external.duffel.models import OfferRequestResponse, StaySearchResponse
from app.external.duffel.validation import validate_duffel_response


def parse_args() -> argparse.Namespace:
    """Read whether the explicitly optional Stays check should run."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-stays",
        action="store_true",
        help="also make the separately optional Duffel Stays request",
    )
    parser.add_argument(
        "--require-stays",
        action="store_true",
        help="check Stays and return nonzero when access is not enabled",
    )
    return parser.parse_args()


async def run(*, check_stays: bool, require_stays: bool) -> int:
    """Run the minimum real test-mode requests without printing credentials."""

    settings = Settings()
    if settings.selected_flight_provider != "duffel" or not settings.duffel_is_configured:
        print("FAIL Duffel configuration: select Duffel Flights and configure its access token")
        return 1
    if settings.duffel_env != "test":
        print("FAIL Duffel environment: this P17 checker only permits test mode")
        return 1
    print("PASS Duffel environment: test")
    client = DuffelClient(
        httpx.AsyncClient(base_url=DUFFEL_API_BASE_URL),
        access_token=settings.duffel_access_token,
        environment=settings.duffel_env,
        api_version=settings.duffel_api_version,
        timeout_seconds=settings.duffel_timeout_seconds,
        max_retries=0,
    )
    check_in = date.today() + timedelta(days=30)
    try:
        flight_payload = await client.post(
            "/air/offer_requests",
            operation="flight_offer_request",
            params={"return_offers": "true", "view": "offers"},
            json={
                "data": {
                    "slices": [
                        {
                            "origin": "LHR",
                            "destination": "DXB",
                            "departure_date": check_in.isoformat(),
                        }
                    ],
                    "passengers": [{"type": "adult"}],
                    "cabin_class": "economy",
                }
            },
        )
        try:
            flights = validate_duffel_response(
                OfferRequestResponse,
                flight_payload,
                operation="flight_offer_request",
            ).data.offers
        except DuffelSchemaError as exc:
            _report_schema_error("Flight", exc)
            return 1
        if not flights:
            print("FAIL Flight offers: Duffel returned zero offers")
            return 1
        print("PASS Flights access")
        print(f"PASS Flight offers: {len(flights)}")
        if not check_stays and not require_stays:
            return 0

        try:
            stays_payload = await client.post(
                "/stays/search",
                operation="stay_search",
                json={
                    "data": {
                        "location": {
                            "radius": 2,
                            "geographic_coordinates": {
                                "latitude": -24.38,
                                "longitude": -128.32,
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
            if exc.code == "duffel_stays_access_denied" and not require_stays:
                print("SKIP Stays: access not enabled")
                return 0
            print(f"FAIL Stays: {exc.code}")
            return 1
        try:
            stays = validate_duffel_response(
                StaySearchResponse,
                stays_payload,
                operation="stay_search",
            ).data.results
        except DuffelSchemaError as exc:
            _report_schema_error("Stays", exc)
            return 1
        if not stays:
            print("FAIL Stay results: Duffel returned zero results")
            return 1
        print("PASS Stays access")
        print(f"PASS Stay results: {len(stays)}")
        return 0
    except DuffelError as exc:
        print(f"FAIL Duffel request: {exc.code}")
        return 1
    finally:
        await client.aclose()


def _report_schema_error(label: str, error: DuffelSchemaError) -> None:
    """Print only value-free validation locations and error types."""

    print(f"FAIL {label} response: {error.code}")
    print(
        "INFO Duffel schema mismatch: "
        f"provider=duffel operation={error.operation} "
        f"validation_error_count={error.error_count}"
    )
    for issue in error.issues:
        print(f"INFO Duffel schema mismatch: loc={issue.loc} type={issue.type}")


def main() -> int:
    """Run the async checker from a normal shell command."""

    args = parse_args()
    return asyncio.run(
        run(
            check_stays=args.check_stays,
            require_stays=args.require_stays,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
