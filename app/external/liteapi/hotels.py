"""Build LiteAPI searches and map bounded, honest single-room hotel candidates."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError

from app.domain.models import HotelOption, TravelDataSource, TripRequirements
from app.external.duffel.locations import ResolvedLocation
from app.external.duffel.mapper import haversine_km
from app.external.liteapi.client import LiteAPIClient
from app.external.liteapi.errors import LiteAPIError
from app.external.liteapi.models import HotelRatesResponse, Offer
from app.external.liteapi.validation import validate_liteapi_response
from app.external.locations import LocationResolver
from app.search.models import JsonObject


def stay_night_count(checkin: date, checkout: date) -> int:
    """Count exclusive-checkout nights, rejecting zero or unsupported stays."""

    nights = (checkout - checkin).days
    if not 1 <= nights <= 366:
        raise LiteAPIError("liteapi_unsupported_request")
    return nights


def hotel_request(
    trip: TripRequirements,
    center: ResolvedLocation,
    *,
    max_hotels: int,
    max_rates_per_hotel: int,
) -> JsonObject:
    """Translate inclusive application days to hotel checkout on the following day."""

    if trip.guest_nationality is None:
        raise LiteAPIError("liteapi_invalid_guest_nationality")
    if trip.travelers not in {1, 2} or trip.end_date == date.max:
        raise LiteAPIError("liteapi_unsupported_request")
    checkout = trip.end_date + timedelta(days=1)
    stay_night_count(trip.start_date, checkout)
    body: JsonObject = {
        "checkin": trip.start_date.isoformat(),
        "checkout": checkout.isoformat(),
        "currency": trip.currency.value,
        "guestNationality": trip.guest_nationality,
        "occupancies": [{"adults": trip.travelers}],
        "roomMapping": True,
        "maxRatesPerHotel": max_rates_per_hotel,
        "includeHotelData": True,
        "limit": max_hotels,
        "timeout": 6,
        "stream": False,
    }
    if center.latitude is not None and center.longitude is not None:
        body.update(latitude=center.latitude, longitude=center.longitude, radius=10000)
    else:
        body["iataCode"] = center.iata_code
    return body


def _offer_total(offer: Offer, currency: str, adults: int) -> Decimal | None:
    if len(offer.rates) != 1:
        return None
    rate = offer.rates[0]
    if rate.adultCount not in {None, adults} or rate.childCount not in {None, 0}:
        return None
    totals = offer.rates[0].retailRate.total
    if len(totals) != 1 or totals[0].currency != currency:
        return None
    total = totals[0].amount
    if offer.offerRetailRate is not None and (
        offer.offerRetailRate.currency != currency or offer.offerRetailRate.amount != total
    ):
        return None
    return total


def map_hotels(
    response: HotelRatesResponse,
    trip: TripRequirements,
    center: ResolvedLocation,
    *,
    max_hotels: int,
    source: TravelDataSource,
) -> list[HotelOption]:
    """Choose the cheapest valid single-room offer per property, then cap candidates."""

    if trip.end_date == date.max:
        raise LiteAPIError("liteapi_unsupported_request")
    nights = stay_night_count(trip.start_date, trip.end_date + timedelta(days=1))
    details = {hotel.id: hotel for hotel in response.hotels}
    candidates: dict[str, HotelOption] = {}
    for entry in response.data:
        hotel = details.get(entry.hotelId)
        if hotel is None:
            continue
        priced = [
            (total, index, offer)
            for index, offer in enumerate(entry.roomTypes)
            if (total := _offer_total(offer, trip.currency.value, trip.travelers)) is not None
        ]
        if not priced:
            continue
        total, _, offer = min(priced, key=lambda item: (item[0], item[1]))
        rate = offer.rates[0]
        policy = rate.cancellationPolicies
        distance = None
        if (
            hotel.location is not None
            and center.latitude is not None
            and center.longitude is not None
        ):
            distance = haversine_km(
                center.latitude, center.longitude, hotel.location.latitude, hotel.location.longitude
            )
        try:
            candidate = HotelOption(
                name=hotel.name,
                city=trip.destination,
                rating=hotel.starRating,
                review_score=hotel.rating,
                currency=trip.currency,
                total_stay_price=total,
                stay_nights=nights,
                price_per_night=(total / Decimal(nights)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                room_name=rate.name,
                board_name=rate.boardName[:120] if rate.boardName else None,
                refundable=(
                    policy.refundableTag == "RFN"
                    if policy and policy.refundableTag is not None
                    else None
                ),
                has_excluded_fees=any(
                    not fee.included for fee in rate.retailRate.taxesAndFees or []
                ),
                distance_to_center_km=distance,
                amenities=(hotel.hotelFacilities or [])[:20],
                provider_hotel_id=hotel.id,
                data_source=source,
            )
        except ValidationError:
            raise LiteAPIError("liteapi_invalid_response") from None
        previous = candidates.get(hotel.id)
        if previous is None or total < (previous.total_stay_price or Decimal("Infinity")):
            candidates[hotel.id] = candidate
    if not candidates:
        raise LiteAPIError(
            "liteapi_no_hotel_rates" if not response.data else "liteapi_invalid_response"
        )
    return sorted(
        candidates.values(),
        key=lambda item: (item.total_stay_price or Decimal(0), item.provider_hotel_id or ""),
    )[:max_hotels]


class LiteAPIHotelProvider:
    """Use one injected location resolver and one lifespan-owned rates client."""

    def __init__(
        self,
        client: LiteAPIClient,
        resolver: LocationResolver,
        *,
        max_hotels: int = 10,
        max_rates_per_hotel: int = 1,
        source: TravelDataSource = TravelDataSource.LITEAPI_SANDBOX,
    ) -> None:
        self.client = client
        self.resolver = resolver
        self.max_hotels = max_hotels
        self.max_rates_per_hotel = max_rates_per_hotel
        self.source = source

    async def search(self, trip: TripRequirements) -> list[HotelOption]:
        """Validate local inputs before resolution or any authenticated HTTP search."""

        if trip.guest_nationality is None:
            raise LiteAPIError("liteapi_invalid_guest_nationality")
        if trip.travelers not in {1, 2}:
            raise LiteAPIError("liteapi_unsupported_request")
        center = await self.resolver.resolve(trip.destination)
        body = hotel_request(
            trip, center, max_hotels=self.max_hotels, max_rates_per_hotel=self.max_rates_per_hotel
        )
        response = validate_liteapi_response(
            HotelRatesResponse, await self.client.hotel_rates(body)
        )
        if response.sandbox is not None and response.sandbox != (
            self.client.environment == "sandbox"
        ):
            raise LiteAPIError("liteapi_invalid_response")
        return map_hotels(response, trip, center, max_hotels=self.max_hotels, source=self.source)
