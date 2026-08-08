"""Tests for deterministic travel-plan assembly."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import Currency, FlightOption, TripRequirements
from app.services.planning_service import (
    MOCK_PLANNING_PROVIDERS,
    PlanningServiceError,
    create_mock_travel_plan,
)


def make_requirements(
    *,
    destination: str = "Tokyo",
    end_date: date = date(2026, 9, 5),
    budget: Decimal = Decimal("10000.00"),
    preferences: list[str] | None = None,
) -> TripRequirements:
    """Build valid requirements with focused overrides for each test."""

    return TripRequirements(
        origin="Shanghai",
        destination=destination,
        start_date=date(2026, 9, 1),
        end_date=end_date,
        budget=budget,
        currency=Currency.CNY,
        travelers=1,
        preferences=preferences or [],
    )


def test_plan_uses_first_flight_highest_rated_hotel_and_all_providers() -> None:
    """The documented selection rules produce a complete Tokyo plan."""

    requirements = make_requirements(preferences=["photography", "vintage shopping"])

    plan = create_mock_travel_plan(requirements)

    flights = MOCK_PLANNING_PROVIDERS.search_flights(requirements)
    hotels = MOCK_PLANNING_PROVIDERS.search_hotels(requirements)
    assert plan.flight == flights[0]
    assert plan.hotel.rating == max(hotel.rating for hotel in hotels)
    assert len(plan.daily_itinerary) == 5
    assert "Arrive in Tokyo" in plan.daily_itinerary[0].activities[0]
    assert "Visit Asakusa Heritage Walk" in plan.daily_itinerary[0].activities[3]
    assert "Weather:" in plan.daily_itinerary[0].activities[-1]
    assert plan.markdown.startswith("# Mock travel plan: Shanghai to Tokyo")


def test_plan_is_destination_agnostic() -> None:
    """Changing the destination changes the generated plan content."""

    paris_plan = create_mock_travel_plan(make_requirements(destination="Paris"))

    assert paris_plan.hotel.city == "Paris"
    assert "Paris" in paris_plan.daily_itinerary[0].title
    assert any(
        "Paris Historic Center Walk" in activity
        for activity in paris_plan.daily_itinerary[0].activities
    )
    assert "Tokyo" not in paris_plan.markdown


@pytest.mark.parametrize(
    ("end_date", "expected_days"),
    [(date(2026, 9, 1), 1), (date(2026, 9, 2), 2), (date(2026, 9, 7), 7)],
)
def test_itinerary_covers_every_inclusive_trip_day(
    end_date: date,
    expected_days: int,
) -> None:
    """One itinerary item is created for every date, including both endpoints."""

    plan = create_mock_travel_plan(make_requirements(end_date=end_date))

    assert len(plan.daily_itinerary) == expected_days
    assert plan.daily_itinerary[-1].date == end_date


def test_total_cost_uses_the_documented_formula_exactly() -> None:
    """Total equals selected flight, hotel days, and daily activity totals."""

    plan = create_mock_travel_plan(make_requirements())
    daily_cost = sum(
        (day.estimated_cost for day in plan.daily_itinerary),
        start=Decimal("0.00"),
    )
    expected = (
        plan.flight.price
        + plan.hotel.price_per_night * Decimal(len(plan.daily_itinerary))
        + daily_cost
    )

    assert plan.total_cost == expected


def test_over_budget_plan_returns_a_warning_instead_of_failing() -> None:
    """A low budget still returns a useful plan with a visible warning."""

    plan = create_mock_travel_plan(make_requirements(budget=Decimal("100.00")))

    assert plan.total_cost > plan.requirements.budget
    assert plan.budget_warning is not None
    assert "exceeds the budget" in plan.budget_warning
    assert plan.budget_warning in plan.markdown


def test_provider_failure_becomes_a_safe_service_error() -> None:
    """Raw provider details remain chained internally but get a safe stage label."""

    def failing_flight_search(requirements: TripRequirements) -> list[FlightOption]:
        del requirements
        raise RuntimeError("private provider detail")

    providers = replace(
        MOCK_PLANNING_PROVIDERS,
        search_flights=failing_flight_search,
    )

    with pytest.raises(PlanningServiceError, match="flight search") as error:
        create_mock_travel_plan(make_requirements(), providers)

    assert isinstance(error.value.__cause__, RuntimeError)


def test_empty_provider_result_is_reported_clearly() -> None:
    """An empty result cannot cause an unclear index error."""

    providers = replace(MOCK_PLANNING_PROVIDERS, search_hotels=lambda requirements: [])

    with pytest.raises(PlanningServiceError, match="hotel selection"):
        create_mock_travel_plan(make_requirements(), providers)


def test_invalid_requirements_are_rejected_before_planning() -> None:
    """Pydantic rejects an impossible date range before a provider can run."""

    with pytest.raises(ValidationError, match="end_date cannot be earlier"):
        TripRequirements(
            origin="Shanghai",
            destination="Tokyo",
            start_date=date(2026, 9, 2),
            end_date=date(2026, 9, 1),
            budget=Decimal("10000.00"),
            currency=Currency.CNY,
            travelers=1,
        )
