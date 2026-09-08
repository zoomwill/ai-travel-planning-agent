"""Deterministic resolution through Duffel's official Places endpoint."""

from dataclasses import dataclass

from app.external.duffel.client import DuffelClient
from app.external.duffel.errors import DuffelError
from app.external.duffel.models import DuffelPlace, PlaceSuggestionsResponse
from app.external.duffel.validation import validate_duffel_response


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    """Shared, provider-backed location for Flights and Stays."""

    name: str
    country_code: str
    city: str
    iata_code: str
    iata_codes: tuple[str, ...]
    latitude: float | None
    longitude: float | None


class DuffelLocationResolver:
    """Resolve user text without LLM guessing or a private airport table."""

    def __init__(self, client: DuffelClient, *, require_coordinates: bool = True) -> None:
        self._client = client
        self._require_coordinates = require_coordinates

    async def resolve(self, query: str) -> ResolvedLocation:
        """Return one unambiguous exact or provider-ranked official suggestion."""

        payload = await self._client.get(
            "/places/suggestions",
            params={"query": query},
            operation="location_lookup",
        )
        response = validate_duffel_response(
            PlaceSuggestionsResponse,
            payload,
            operation="location_lookup",
        )
        if not response.data:
            raise DuffelError("duffel_location_not_found")

        matches = self._best_matches(query, response.data)
        if len(matches) != 1:
            raise DuffelError("duffel_location_not_found")
        place = matches[0]
        latitude, longitude = self._coordinates(place)
        if self._require_coordinates and (latitude is None or longitude is None):
            raise DuffelError("duffel_location_not_found")
        airport_codes = tuple(
            dict.fromkeys(
                [place.iata_code, *(airport.iata_code for airport in place.airports or [])]
            )
        )
        return ResolvedLocation(
            name=place.name,
            country_code=place.iata_country_code,
            city=place.city_name or place.name,
            iata_code=place.iata_code,
            iata_codes=airport_codes,
            latitude=latitude,
            longitude=longitude,
        )

    @staticmethod
    def _best_matches(query: str, places: list[DuffelPlace]) -> list[DuffelPlace]:
        normalized = query.casefold().strip()
        exact_code = [place for place in places if place.iata_code.casefold() == normalized]
        if exact_code:
            return exact_code[:1]
        exact_name = [place for place in places if place.name.casefold() == normalized]
        if exact_name:
            city_matches = [place for place in exact_name if place.type == "city"]
            return city_matches or exact_name
        return places[:1]

    @staticmethod
    def _coordinates(place: DuffelPlace) -> tuple[float | None, float | None]:
        if place.latitude is not None and place.longitude is not None:
            return place.latitude, place.longitude
        coordinates = [
            (airport.latitude, airport.longitude)
            for airport in place.airports or []
            if airport.latitude is not None and airport.longitude is not None
        ]
        if not coordinates:
            return None, None
        latitude = sum(item[0] for item in coordinates) / len(coordinates)
        longitude = sum(item[1] for item in coordinates) / len(coordinates)
        return latitude, longitude
