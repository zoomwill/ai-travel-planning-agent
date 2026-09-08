"""Strict projections of only the Duffel response fields used by P17."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _require_duration_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Duffel duration must be an ISO 8601 string")
    return value


DuffelDuration = Annotated[
    timedelta,
    BeforeValidator(_require_duration_string),
    Field(gt=timedelta(0)),
]


class DuffelResponseModel(BaseModel):
    """Ignore unrelated provider fields while validating every field we consume."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class DuffelAirportSummary(DuffelResponseModel):
    """Airport nested inside a city suggestion."""

    name: str = Field(min_length=1)
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class DuffelPlace(DuffelResponseModel):
    """One official Places suggestion used for both Flights and Stays."""

    type: Literal["airport", "city"]
    name: str = Field(min_length=1)
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    iata_country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    city_name: str | None = None
    airports: list[DuffelAirportSummary] | None = None


class PlaceSuggestionsResponse(DuffelResponseModel):
    """Top-level Places response."""

    data: list[DuffelPlace]


class DuffelCarrier(DuffelResponseModel):
    """Operating carrier identity required for truthful display."""

    name: str = Field(min_length=1)
    iata_code: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2}$")


class DuffelFlightPlace(DuffelResponseModel):
    """Minimal airport or city endpoint inside a flight segment."""

    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    time_zone: str | None = Field(default=None, min_length=1)


class DuffelSegment(DuffelResponseModel):
    """Minimal operating segment returned inside an offer."""

    id: str = Field(min_length=1)
    operating_carrier: DuffelCarrier
    operating_carrier_flight_number: str | None = Field(default=None, min_length=1)
    marketing_carrier: DuffelCarrier
    marketing_carrier_flight_number: str = Field(min_length=1)
    origin: DuffelFlightPlace
    destination: DuffelFlightPlace
    departing_at: datetime
    arriving_at: datetime
    duration: DuffelDuration | None = None


class DuffelSlice(DuffelResponseModel):
    """One requested journey direction and its operating segments."""

    duration: DuffelDuration | None = None
    segments: list[DuffelSegment] = Field(min_length=1)


class DuffelOffer(DuffelResponseModel):
    """Offer facts that are safe to map into the local domain."""

    id: str = Field(min_length=1)
    total_amount: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    total_currency: str = Field(pattern=r"^[A-Z]{3}$")
    expires_at: datetime | None = None
    slices: list[DuffelSlice] = Field(min_length=1)


class DuffelOfferRequest(DuffelResponseModel):
    """Created offer request with embedded offers."""

    offers: list[DuffelOffer]


class OfferRequestResponse(DuffelResponseModel):
    """Top-level Flight Offer Request response."""

    data: DuffelOfferRequest


class GeographicCoordinates(DuffelResponseModel):
    """Validated decimal-degree coordinates."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class StayLocation(DuffelResponseModel):
    """Optional accommodation coordinates."""

    geographic_coordinates: GeographicCoordinates | None = None


class StayAmenity(DuffelResponseModel):
    """Provider amenity with a human-readable fallback."""

    type: str = Field(min_length=1)
    description: str | None = None


class DuffelAccommodation(DuffelResponseModel):
    """Accommodation facts used by the local hotel projection."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_score: float | None = Field(default=None, ge=0, le=10)
    amenities: list[StayAmenity] | None = None
    location: StayLocation | None = None


class DuffelStayResult(DuffelResponseModel):
    """One cheapest-rate result from a Stays search."""

    id: str = Field(min_length=1)
    cheapest_rate_total_amount: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    cheapest_rate_currency: str = Field(pattern=r"^[A-Z]{3}$")
    accommodation: DuffelAccommodation


class DuffelStaySearch(DuffelResponseModel):
    """Created Stays search with its result list."""

    results: list[DuffelStayResult] = Field(default_factory=list)


class StaySearchResponse(DuffelResponseModel):
    """Top-level Stays search response."""

    data: DuffelStaySearch
