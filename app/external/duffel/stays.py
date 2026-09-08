"""Duffel Stays search-only provider."""

from datetime import timedelta

from app.domain.models import HotelOption, TravelDataSource, TripRequirements
from app.external.duffel.client import DuffelClient
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import DuffelLocationResolver
from app.external.duffel.mapper import map_stay_result
from app.external.duffel.models import StaySearchResponse
from app.external.duffel.validation import validate_duffel_response


class DuffelStayProvider:
    """Search one room for one or two adults without entering booking flows."""

    def __init__(
        self,
        client: DuffelClient,
        resolver: DuffelLocationResolver,
        *,
        max_results: int,
        source: TravelDataSource,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._max_results = max_results
        self._source = source

    async def search(self, requirements: TripRequirements) -> list[HotelOption]:
        """Map an inclusive trip end date to the provider's exclusive checkout date."""

        if requirements.travelers not in {1, 2}:
            raise DuffelError("duffel_unsupported_request")
        destination = await self._resolver.resolve(requirements.destination)
        if destination.latitude is None or destination.longitude is None:
            raise DuffelError("duffel_location_not_found")
        checkout = requirements.end_date + timedelta(days=1)
        nights = (checkout - requirements.start_date).days
        payload = await self._client.post(
            "/stays/search",
            operation="stay_search",
            json={
                "data": {
                    "location": {
                        "radius": 5,
                        "geographic_coordinates": {
                            "latitude": destination.latitude,
                            "longitude": destination.longitude,
                        },
                    },
                    "check_in_date": requirements.start_date.isoformat(),
                    "check_out_date": checkout.isoformat(),
                    "guests": [{"type": "adult"} for _ in range(requirements.travelers)],
                    "rooms": 1,
                }
            },
        )
        response = validate_duffel_response(
            StaySearchResponse,
            payload,
            operation="stay_search",
        )
        if not response.data.results:
            raise DuffelError("duffel_no_stay_results")
        return [
            map_stay_result(result, requirements, destination, nights, self._source)
            for result in response.data.results[: self._max_results]
        ]
