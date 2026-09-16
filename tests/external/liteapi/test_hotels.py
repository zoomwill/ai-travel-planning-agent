"""Provider-shaped mapping, exact price, date, and nationality regressions."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import HotelOption, TravelDataSource, TravelDataSources, TripRequirements
from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import DuffelLocationResolver, ResolvedLocation
from app.external.liteapi.errors import LiteAPIError, LiteAPISchemaError
from app.external.liteapi.hotels import (
    LiteAPIHotelProvider,
    hotel_request,
    map_hotels,
    stay_night_count,
)
from app.external.liteapi.models import HotelRatesResponse
from app.external.liteapi.validation import validate_liteapi_response
from app.intake.logic import (
    merge_requirement_patch,
    missing_requirement_fields,
    require_explicit_nationality,
)
from app.intake.models import (
    PartialTripRequirements,
    RequirementField,
    TripRequirementPatch,
    complete_trip_requirements,
)
from app.services.mock_providers import get_weather, search_attractions, search_flights
from app.services.planning_service import assemble_travel_plan_from_results
from tests.external.liteapi.helpers import Resolver, client, offer, payload, response, trip


async def mapped(value=None, **updates):
    requirements = trip(**updates)
    center = await Resolver().resolve(requirements.destination)
    result = validate_liteapi_response(HotelRatesResponse, value or payload())
    return map_hotels(
        result, requirements, center, max_hotels=5, source=TravelDataSource.LITEAPI_SANDBOX
    )


@pytest.mark.parametrize("adults", [1, 2])
async def test_exact_hotel_request(adults):
    requests = []

    def handler(request):
        import json

        requests.append(json.loads(request.content))
        return response()

    api = client(handler)
    provider = LiteAPIHotelProvider(api, Resolver(), max_hotels=5, max_rates_per_hotel=2)
    await provider.search(
        trip(travelers=adults, start_date=date(2027, 10, 12), end_date=date(2027, 10, 16))
    )
    await api.aclose()
    assert requests == [
        {
            "checkin": "2027-10-12",
            "checkout": "2027-10-17",
            "currency": "USD",
            "guestNationality": "US",
            "occupancies": [{"adults": adults}],
            "roomMapping": True,
            "maxRatesPerHotel": 2,
            "includeHotelData": True,
            "limit": 5,
            "timeout": 6,
            "stream": False,
            "latitude": 35.67,
            "longitude": 139.65,
            "radius": 10000,
        }
    ]


def test_iata_request_when_coordinates_are_absent():
    center = ResolvedLocation("Tokyo", "JP", "Tokyo", "TYO", ("TYO",), None, None)
    body = hotel_request(trip(), center, max_hotels=5, max_rates_per_hotel=1)
    assert body["iataCode"] == "TYO"
    assert "latitude" not in body


async def test_shared_resolver_can_explicitly_use_provider_iata_without_coordinates():
    import httpx

    from tests.external.duffel.helpers import make_client, place

    location = place("Tokyo", "TYO", latitude=35.67, longitude=139.65)
    location.update(latitude=None, longitude=None, airports=None)
    api = make_client(lambda _: httpx.Response(200, json={"data": [location]}))
    try:
        with pytest.raises(DuffelError, match="duffel_location_not_found"):
            await DuffelLocationResolver(api).resolve("Tokyo")
        center = await DuffelLocationResolver(api, require_coordinates=False).resolve("Tokyo")
        body = hotel_request(trip(), center, max_hotels=5, max_rates_per_hotel=1)
        assert body["iataCode"] == "TYO"
        assert "latitude" not in body
    finally:
        await api.aclose()


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"guest_nationality": None}, "liteapi_invalid_guest_nationality"),
        ({"travelers": 3}, "liteapi_unsupported_request"),
    ],
)
async def test_invalid_request_makes_no_http(updates, code):
    api = client(lambda _: pytest.fail("must not call provider"))
    try:
        with pytest.raises(LiteAPIError, match=code):
            await LiteAPIHotelProvider(api, Resolver()).search(trip(**updates))
    finally:
        await api.aclose()


async def test_cheapest_valid_offer_not_first_and_bounded_candidates():
    value = payload(30)
    value["data"][0]["roomTypes"] = [offer("900"), offer("100", currency="EUR"), offer("301.01")]
    hotels = await mapped(value, start_date=date(2027, 10, 12), end_date=date(2027, 10, 16))
    assert len(hotels) == 5
    assert hotels[0].total_stay_price == Decimal("301.01")
    assert hotels[0].price_per_night == Decimal("60.20")
    assert hotels[0].stay_nights == 5
    assert hotels[0].rating == 4
    assert hotels[0].review_score == 8.8
    assert hotels[0].room_name == "Standard Room"
    assert hotels[0].board_name == "Room Only"
    assert hotels[0].refundable is True
    assert hotels[0].has_excluded_fees is True
    assert hotels[0].distance_to_center_km > 0
    assert "fake-volatile" not in hotels[0].model_dump_json()


async def test_duplicate_property_compares_exact_total_not_rounded_average():
    value = payload()
    value["data"] = [
        {"hotelId": "fake-hotel-0", "roomTypes": [offer("501.02")]},
        {"hotelId": "fake-hotel-0", "roomTypes": [offer("501.01")]},
    ]
    hotels = await mapped(value, start_date=date(2027, 10, 12), end_date=date(2027, 10, 16))
    assert len(hotels) == 1
    assert hotels[0].total_stay_price == Decimal("501.01")
    assert hotels[0].price_per_night == Decimal("100.20")


@pytest.mark.parametrize("counts", [{"adultCount": 2}, {"childCount": 1}])
async def test_wrong_occupancy_cannot_become_a_candidate(counts):
    value = payload()
    value["data"][0]["roomTypes"][0]["rates"][0].update(counts)
    with pytest.raises(LiteAPIError, match="liteapi_invalid_response"):
        await mapped(value, travelers=1)


@pytest.mark.parametrize(
    "updates", [{"total_stay_price": None}, {"stay_nights": None}, {"price_per_night": "1"}]
)
async def test_domain_rejects_inconsistent_exact_quote(updates):
    hotel = (await mapped())[0]
    with pytest.raises(ValidationError):
        HotelOption.model_validate({**hotel.model_dump(), **updates})


@pytest.mark.parametrize(
    "fees,expected",
    [(None, False), ([], False), ([{"included": True}], False), ([{"included": False}], True)],
)
async def test_included_fees_never_double_counted(fees, expected):
    value = payload()
    value["data"][0]["roomTypes"][0]["rates"][0]["retailRate"]["taxesAndFees"] = fees
    hotel = (await mapped(value))[0]
    assert hotel.total_stay_price == Decimal("501.01")
    assert hotel.has_excluded_fees is expected


async def test_nullable_or_absent_display_metadata_is_not_invented():
    value = payload()
    value["hotels"][0] = {
        "id": "fake-hotel-0",
        "name": "Fake Hotel",
        "rating": None,
        "starRating": None,
    }
    hotel = (await mapped(value))[0]
    assert hotel.rating is None and hotel.review_score is None
    assert hotel.amenities == []
    assert hotel.distance_to_center_km is None


async def test_currency_mismatch_and_inconsistent_totals_rejected():
    for bad in (offer("501.01", currency="EUR"), offer("500")):
        value = payload()
        value["data"][0]["roomTypes"] = [bad]
        if bad["offerRetailRate"]["currency"] == "USD":
            bad["offerRetailRate"]["amount"] = Decimal("999")
        with pytest.raises(LiteAPIError, match="liteapi_invalid_response"):
            await mapped(value)


@pytest.mark.parametrize("amount", ["not-money", True, Decimal("NaN"), 0, -1])
def test_consumed_amounts_remain_strict(amount):
    value = payload()
    value["data"][0]["roomTypes"][0]["offerRetailRate"]["amount"] = amount
    with pytest.raises(LiteAPISchemaError):
        validate_liteapi_response(HotelRatesResponse, value)


async def test_empty_rates_are_not_pass_or_demo():
    with pytest.raises(LiteAPIError, match="liteapi_no_hotel_rates"):
        await mapped({"data": [], "hotels": []})


@pytest.mark.parametrize(
    "message", ["CN", "cn", "nationality: CN", "my nationality is CN", "国籍：CN"]
)
def test_nationality_requires_explicit_current_message(message):
    patch = TripRequirementPatch(guest_nationality="CN", destination="Tokyo")
    assert require_explicit_nationality(message, patch) == patch


@pytest.mark.parametrize(
    "message", ["from US to Tokyo", "English locale", "do not use nationality: US"]
)
def test_model_cannot_infer_nationality_from_origin_or_locale(message):
    patch = TripRequirementPatch(guest_nationality="US", destination="Tokyo")
    safe = require_explicit_nationality(message, patch)
    assert "guest_nationality" not in safe.model_fields_set
    assert safe.destination == "Tokyo"


@pytest.mark.parametrize(
    "value,expected", [("US", "US"), ("CN", "CN"), ("jp", "JP"), (" FR ", "FR")]
)
def test_nationality_is_explicit_and_normalized(value, expected):
    assert (
        TripRequirements.model_validate(
            {**trip().model_dump(), "guest_nationality": value}
        ).guest_nationality
        == expected
    )


@pytest.mark.parametrize("value", ["", "U", "USA", "12", "ZZ", 12, True])
def test_invalid_nationality_rejected(value):
    with pytest.raises(ValidationError):
        TripRequirements.model_validate({**trip().model_dump(), "guest_nationality": value})


async def test_intake_to_daily_plan_to_hotel_price_date_contract():
    draft = merge_requirement_patch(
        PartialTripRequirements(),
        TripRequirementPatch(
            origin="Cleveland",
            destination="Tokyo",
            start_date=date(2027, 10, 12),
            duration_days=5,
            budget=10000,
            currency="USD",
            travelers=1,
        ),
    )
    assert draft.end_date == date(2027, 10, 16)
    assert missing_requirement_fields(draft) == []
    assert missing_requirement_fields(draft, require_guest_nationality=True) == [
        RequirementField.GUEST_NATIONALITY
    ]
    draft = merge_requirement_patch(draft, TripRequirementPatch(guest_nationality="US"))
    requirements = complete_trip_requirements(draft)
    hotel = (await mapped(start_date=requirements.start_date, end_date=requirements.end_date))[0]
    plan = assemble_travel_plan_from_results(
        requirements=requirements,
        flight_options=search_flights(requirements),
        hotel_options=[hotel],
        attractions=search_attractions(requirements),
        weather=get_weather(requirements),
        route=None,
        data_sources=TravelDataSources(hotels=TravelDataSource.LITEAPI_SANDBOX),
    )
    assert [day.date.day for day in plan.daily_itinerary] == [12, 13, 14, 15, 16]
    body = hotel_request(
        requirements, await Resolver().resolve("Tokyo"), max_hotels=5, max_rates_per_hotel=1
    )
    assert body["checkout"] == "2027-10-17"
    assert hotel.stay_nights == len(plan.daily_itinerary) == 5
    assert hotel.price_per_night == Decimal("100.20")
    assert "outbound one-way only" in plan.markdown
    assert "return flight is not included" in plan.markdown
    assert plan.total_cost - plan.flight.price - sum(
        day.estimated_cost for day in plan.daily_itinerary
    ) == Decimal("501.01")
    with pytest.raises(LiteAPIError):
        stay_night_count(requirements.start_date, requirements.start_date)
