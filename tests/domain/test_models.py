"""Validation tests for all Phase P03 domain models."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.models import (
    Attraction,
    Currency,
    DailyItinerary,
    FlightOption,
    HotelOption,
    QualityScore,
    RouteSummary,
    ToolError,
    TransportMode,
    TravelPlan,
    TripRequirements,
    WeatherSummary,
)


def make_requirements(**overrides: object) -> TripRequirements:
    """Build valid requirements while allowing one field to change."""

    values: dict[str, object] = {
        "origin": "Shanghai",
        "destination": "Tokyo",
        "start_date": date(2027, 4, 10),
        "end_date": date(2027, 4, 13),
        "budget": Decimal("12000.00"),
        "currency": Currency.CNY,
        "travelers": 2,
        "preferences": ["local food", "museums"],
    }
    values.update(overrides)
    return TripRequirements.model_validate(values)


def make_flight(**overrides: object) -> FlightOption:
    """Build a valid flight while allowing one field to change."""

    values: dict[str, object] = {
        "flight_number": "MK318",
        "airline": "Mock Pacific",
        "origin": "Shanghai",
        "destination": "Tokyo",
        "departure_time": datetime(2027, 4, 10, 8, 30),
        "arrival_time": datetime(2027, 4, 10, 11, 30),
        "duration_minutes": 180,
        "price": Decimal("1800.00"),
        "currency": Currency.CNY,
    }
    values.update(overrides)
    return FlightOption.model_validate(values)


def make_hotel(**overrides: object) -> HotelOption:
    """Build a valid hotel while allowing one field to change."""

    values: dict[str, object] = {
        "name": "Tokyo Central Hotel",
        "city": "Tokyo",
        "rating": 4.5,
        "price_per_night": Decimal("780.00"),
        "currency": Currency.CNY,
        "distance_to_center_km": 1.2,
        "amenities": ["Wi-Fi", "breakfast"],
    }
    values.update(overrides)
    return HotelOption.model_validate(values)


def make_day(**overrides: object) -> DailyItinerary:
    """Build a valid itinerary day while allowing one field to change."""

    values: dict[str, object] = {
        "day_number": 1,
        "date": date(2027, 4, 10),
        "title": "Arrival and old Tokyo",
        "activities": ["Hotel check-in", "Asakusa Heritage Walk"],
        "estimated_cost": Decimal("320.00"),
        "currency": Currency.CNY,
    }
    values.update(overrides)
    return DailyItinerary.model_validate(values)


def test_all_models_accept_valid_data() -> None:
    requirements = make_requirements()
    flight = make_flight()
    hotel = make_hotel()
    day = make_day()
    attraction = Attraction(
        name="Asakusa Heritage Walk",
        city="Tokyo",
        category="culture",
        description="A mock self-guided walk.",
        estimated_cost=Decimal("0.00"),
        currency=Currency.CNY,
        opening_hours="09:00-18:00",
    )
    weather = WeatherSummary(
        date=date(2027, 4, 10),
        city="Tokyo",
        condition="Sunny",
        temperature_celsius=19.5,
        rain_probability=15,
    )
    route = RouteSummary(
        origin="Tokyo Station",
        destination="Asakusa",
        transport_mode=TransportMode.PUBLIC_TRANSIT,
        duration_minutes=24,
        estimated_cost=Decimal("18.00"),
        currency=Currency.CNY,
    )
    plan = TravelPlan(
        requirements=requirements,
        flight=flight,
        hotel=hotel,
        daily_itinerary=[day],
        total_cost=Decimal("4460.00"),
        currency=Currency.CNY,
    )
    score = QualityScore(
        completeness=92,
        feasibility=86,
        personalization=88,
        budget_fit=90,
        overall_score=89,
        critique="Add airport transfer time.",
    )
    error = ToolError(
        tool_name="search_flights",
        error_type="unsupported_route",
        message="Origin and destination must be different.",
        recoverable=False,
    )

    assert plan.requirements == requirements
    assert attraction.estimated_cost == Decimal("0.00")
    assert weather.rain_probability == 15
    assert route.transport_mode is TransportMode.PUBLIC_TRANSIT
    assert score.overall_score == 89
    assert error.recoverable is False


def test_end_date_cannot_precede_start_date() -> None:
    with pytest.raises(ValidationError, match="end_date cannot be earlier"):
        make_requirements(end_date=date(2027, 4, 9))


@pytest.mark.parametrize(
    ("field", "value"),
    [("budget", Decimal("0")), ("budget", Decimal("-1")), ("travelers", 0)],
)
def test_budget_and_travelers_must_be_positive(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_requirements(**{field: value})


def test_currency_must_be_supported() -> None:
    with pytest.raises(ValidationError):
        make_requirements(currency="GBP")


@pytest.mark.parametrize(
    "field",
    ["completeness", "feasibility", "personalization", "budget_fit", "overall_score"],
)
@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_every_quality_score_stays_between_zero_and_one_hundred(
    field: str,
    value: float,
) -> None:
    values: dict[str, object] = {
        "completeness": 80,
        "feasibility": 80,
        "personalization": 80,
        "budget_fit": 80,
        "overall_score": 80,
        "critique": "",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        QualityScore.model_validate(values)


@pytest.mark.parametrize("probability", [-1, 101])
def test_rain_probability_stays_between_zero_and_one_hundred(probability: int) -> None:
    with pytest.raises(ValidationError):
        WeatherSummary(
            date=date(2027, 4, 10),
            city="Tokyo",
            condition="Rain",
            temperature_celsius=15,
            rain_probability=probability,
        )


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="destination"):
        TripRequirements.model_validate(
            {
                "origin": "Shanghai",
                "start_date": "2027-04-10",
                "end_date": "2027-04-13",
                "budget": "12000",
                "travelers": 2,
            }
        )


def test_preferences_default_is_not_shared_between_models() -> None:
    first = make_requirements(preferences=[])
    second = make_requirements(preferences=[])

    first.preferences.append("gardens")

    assert second.preferences == []


def test_result_model_boundary_constraints() -> None:
    with pytest.raises(ValidationError):
        make_flight(price=Decimal("0"))
    with pytest.raises(ValidationError):
        make_flight(duration_minutes=0)
    with pytest.raises(ValidationError, match="arrival_time"):
        make_flight(arrival_time=datetime(2027, 4, 10, 8, 0))
    with pytest.raises(ValidationError):
        make_hotel(rating=5.1)
    with pytest.raises(ValidationError):
        make_hotel(price_per_night=Decimal("0"))
    with pytest.raises(ValidationError):
        make_day(day_number=0)


def test_travel_plan_requires_at_least_one_day() -> None:
    with pytest.raises(ValidationError):
        TravelPlan(
            requirements=make_requirements(),
            flight=make_flight(),
            hotel=make_hotel(),
            daily_itinerary=[],
            total_cost=Decimal("4460.00"),
            currency=Currency.CNY,
        )


def test_travel_plan_rejects_currency_and_date_mismatches() -> None:
    with pytest.raises(ValidationError, match="plan currency"):
        TravelPlan(
            requirements=make_requirements(),
            flight=make_flight(currency=Currency.USD),
            hotel=make_hotel(),
            daily_itinerary=[make_day()],
            total_cost=Decimal("4460.00"),
            currency=Currency.CNY,
        )

    with pytest.raises(ValidationError, match="trip dates"):
        TravelPlan(
            requirements=make_requirements(),
            flight=make_flight(),
            hotel=make_hotel(),
            daily_itinerary=[make_day(date=date(2027, 4, 14))],
            total_cost=Decimal("4460.00"),
            currency=Currency.CNY,
        )


def test_tool_error_forbids_traceback_field() -> None:
    with pytest.raises(ValidationError, match="traceback"):
        ToolError.model_validate(
            {
                "tool_name": "search_flights",
                "error_type": "provider_error",
                "message": "Safe message",
                "recoverable": True,
                "traceback": "private stack details",
            }
        )


@pytest.mark.parametrize(
    "model_type",
    [
        TripRequirements,
        FlightOption,
        HotelOption,
        Attraction,
        WeatherSummary,
        RouteSummary,
        DailyItinerary,
        TravelPlan,
        QualityScore,
        ToolError,
    ],
)
def test_every_domain_model_has_field_descriptions_and_example(
    model_type: type[BaseModel],
) -> None:
    assert all(field.description for field in model_type.model_fields.values())
    assert model_type.model_json_schema().get("examples")
