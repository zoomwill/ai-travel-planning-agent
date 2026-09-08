"""Map validated Duffel projections into stable local domain models."""

import math
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from app.domain.models import (
    Currency,
    FlightOption,
    FlightSegment,
    HotelOption,
    TravelDataSource,
    TripRequirements,
)
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import ResolvedLocation
from app.external.duffel.models import DuffelOffer, DuffelSegment, DuffelStayResult


def map_flight_offer(
    offer: DuffelOffer,
    requirements: TripRequirements,
    source: TravelDataSource,
) -> FlightOption:
    """Map one one-way offer and preserve every operating segment."""

    if len(offer.slices) != 1:
        raise DuffelError("duffel_invalid_response")
    slice_ = offer.slices[0]
    try:
        segments = [_map_flight_segment(segment) for segment in slice_.segments]
        currency = Currency(offer.total_currency)
        if currency is not requirements.currency:
            raise DuffelError("duffel_unsupported_request")
        amount = Decimal(offer.total_amount)
        first = segments[0]
        last = segments[-1]
        return FlightOption(
            flight_number=first.flight_number,
            airline=first.airline,
            origin=requirements.origin,
            destination=requirements.destination,
            departure_time=first.departure_time,
            arrival_time=last.arrival_time,
            duration_minutes=_duration_minutes(
                slice_.duration,
                first.departure_time,
                last.arrival_time,
            ),
            price=amount,
            currency=currency,
            segments=segments,
            stops=len(segments) - 1,
            provider_offer_id=offer.id,
            expires_at=offer.expires_at,
            data_source=source,
        )
    except (InvalidOperation, ValidationError, ValueError, ZoneInfoNotFoundError):
        raise DuffelError("duffel_invalid_response") from None


def map_stay_result(
    result: DuffelStayResult,
    requirements: TripRequirements,
    center: ResolvedLocation,
    nights: int,
    source: TravelDataSource,
) -> HotelOption:
    """Map a total-stay price into the existing truthful nightly projection."""

    try:
        currency = Currency(result.cheapest_rate_currency)
        if currency is not requirements.currency:
            raise DuffelError("duffel_unsupported_request")
        total = Decimal(result.cheapest_rate_total_amount)
        nightly = (total / Decimal(nights)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        accommodation = result.accommodation
        coordinates = (
            accommodation.location.geographic_coordinates
            if accommodation.location is not None
            else None
        )
        distance = (
            haversine_km(
                center.latitude,
                center.longitude,
                coordinates.latitude,
                coordinates.longitude,
            )
            if coordinates is not None
            and center.latitude is not None
            and center.longitude is not None
            else None
        )
        amenities = [
            amenity.description or amenity.type.replace("_", " ").title()
            for amenity in accommodation.amenities or []
        ]
        return HotelOption(
            name=accommodation.name,
            city=requirements.destination,
            rating=accommodation.rating,
            review_score=accommodation.review_score,
            price_per_night=nightly,
            currency=currency,
            distance_to_center_km=distance,
            amenities=amenities,
            provider_hotel_id=accommodation.id,
            provider_search_result_id=result.id,
            data_source=source,
        )
    except (InvalidOperation, ValidationError, ValueError, ZeroDivisionError):
        raise DuffelError("duffel_invalid_response") from None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance rounded for display, not provider truth."""

    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return round(radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _flight_number(carrier_code: str | None, number: str) -> str:
    normalized_number = number.strip()
    if carrier_code is None or normalized_number.upper().startswith(carrier_code):
        return normalized_number
    return f"{carrier_code}{normalized_number}"


def _map_flight_segment(segment: DuffelSegment) -> FlightSegment:
    departure = _provider_datetime(segment.departing_at, segment.origin.time_zone)
    arrival = _provider_datetime(segment.arriving_at, segment.destination.time_zone)
    carrier_code, flight_number = _segment_flight_number(segment)
    return FlightSegment(
        flight_number=_flight_number(carrier_code, flight_number),
        airline=segment.operating_carrier.name,
        origin_iata_code=segment.origin.iata_code,
        destination_iata_code=segment.destination.iata_code,
        departure_time=departure,
        arrival_time=arrival,
        duration_minutes=_duration_minutes(segment.duration, departure, arrival),
    )


def _provider_datetime(value: datetime, time_zone: str | None) -> datetime:
    if value.utcoffset() is not None or time_zone is None:
        return value
    return value.replace(tzinfo=ZoneInfo(time_zone))


def _segment_flight_number(segment: DuffelSegment) -> tuple[str | None, str]:
    if segment.operating_carrier_flight_number is not None:
        return segment.operating_carrier.iata_code, segment.operating_carrier_flight_number
    return segment.marketing_carrier.iata_code, segment.marketing_carrier_flight_number


def _duration_minutes(
    value: timedelta | None,
    departure: datetime,
    arrival: datetime,
) -> int:
    if value is None:
        if departure.utcoffset() is None or arrival.utcoffset() is None:
            raise DuffelError("duffel_invalid_response")
        value = arrival.astimezone(UTC) - departure.astimezone(UTC)
    seconds = value.total_seconds()
    minutes, remainder = divmod(seconds, 60)
    if minutes <= 0 or remainder != 0:
        raise DuffelError("duffel_invalid_response")
    return int(minutes)


def validate_offer_time(value: datetime) -> datetime:
    """Retain a typed seam for tests that exercise provider timestamps."""

    return value
