"""Clearly fake, provider-shaped fixtures with realistic envelope nesting."""

from decimal import Decimal

import httpx
from pydantic import SecretStr

from app.external.duffel.locations import ResolvedLocation
from app.external.liteapi.client import LITEAPI_BASE_URL, LiteAPIClient
from tests.external.duffel.helpers import requirements

FAKE_KEY = "sand_unit_only_not_a_real_key"


def trip(**updates):
    """Use an explicitly supplied test nationality, never a production default."""
    return requirements().model_copy(update={"guest_nationality": "US", **updates})


class Resolver:
    """Return test coordinates without a network location lookup."""

    async def resolve(self, query):
        return ResolvedLocation(query, "JP", query, "TYO", ("TYO",), 35.67, 139.65)


def offer(amount="501.01", *, currency="USD", excluded=True):
    """Include ignored vendor fields and the actual one-room price hierarchy."""
    return {
        "offerId": "fake-volatile-offer-id",
        "supplier": "Nuitee",
        "supplierId": 2,
        "offerRetailRate": {"amount": Decimal(amount), "currency": currency},
        "rates": [
            {
                "rateId": "fake-rate-id",
                "name": "Standard Room",
                "boardName": "Room Only",
                "retailRate": {
                    "total": [{"amount": Decimal(amount), "currency": currency}],
                    "taxesAndFees": [
                        {
                            "included": not excluded,
                            "description": "Fake property fee",
                            "amount": 10,
                            "currency": currency,
                        }
                    ],
                },
                "cancellationPolicies": {"refundableTag": "RFN", "hotelRemarks": []},
            }
        ],
    }


def payload(count=1):
    """Match data[] prices to top-level hotels[] metadata, not invented nesting."""
    return {
        "data": [{"hotelId": f"fake-hotel-{n}", "roomTypes": [offer()]} for n in range(count)],
        "hotels": [
            {
                "id": f"fake-hotel-{n}",
                "name": f"Fake Hotel {n}",
                "rating": 8.8,
                "starRating": 4,
                "main_photo": "unused",
                "hotelFacilities": ["WiFi"],
                "location": {"latitude": 35.68, "longitude": 139.66},
            }
            for n in range(count)
        ],
        "sandbox": True,
        "guestLevel": 0,
    }


def client(handler, **kwargs):
    """Inject MockTransport without weakening the production host."""
    return LiteAPIClient(
        httpx.AsyncClient(base_url=LITEAPI_BASE_URL, transport=httpx.MockTransport(handler)),
        api_key=SecretStr(FAKE_KEY),
        **kwargs,
    )


def response(value=None, status=200, headers=None):
    """Encode fixture Decimal as exact JSON numeric lexemes for the HTTP boundary."""
    import json

    # Decimal values are converted only in fake transport serialization.
    return httpx.Response(
        status,
        content=json.dumps(value if value is not None else payload(), default=float),
        headers=headers,
    )
