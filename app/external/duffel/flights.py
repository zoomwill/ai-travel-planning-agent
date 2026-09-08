"""Duffel Flight Offer Request provider."""

from app.domain.models import FlightOption, TravelDataSource, TripRequirements
from app.external.duffel.client import DuffelClient
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import DuffelLocationResolver
from app.external.duffel.mapper import map_flight_offer
from app.external.duffel.models import OfferRequestResponse
from app.external.duffel.validation import validate_duffel_response


class DuffelFlightProvider:
    """Search one-way offers and map a bounded number into local models."""

    def __init__(
        self,
        client: DuffelClient,
        resolver: DuffelLocationResolver,
        *,
        max_offers: int,
        source: TravelDataSource,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._max_offers = max_offers
        self._source = source

    async def search(self, requirements: TripRequirements) -> list[FlightOption]:
        """Resolve both places, create one offer request, and map its offers."""

        origin = await self._resolver.resolve(requirements.origin)
        destination = await self._resolver.resolve(requirements.destination)
        payload = await self._client.post(
            "/air/offer_requests",
            operation="flight_offer_request",
            params={"return_offers": "true", "view": "offers"},
            json={
                "data": {
                    "slices": [
                        {
                            "origin": origin.iata_code,
                            "destination": destination.iata_code,
                            "departure_date": requirements.start_date.isoformat(),
                        }
                    ],
                    "passengers": [{"type": "adult"} for _ in range(requirements.travelers)],
                    "cabin_class": "economy",
                }
            },
        )
        response = validate_duffel_response(
            OfferRequestResponse,
            payload,
            operation="flight_offer_request",
        )
        if not response.data.offers:
            raise DuffelError("duffel_no_flight_offers")
        return [
            map_flight_offer(offer, requirements, self._source)
            for offer in response.data.offers[: self._max_offers]
        ]
