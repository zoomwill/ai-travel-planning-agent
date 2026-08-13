"""Tests proving RevisionPolicy changes structured plan choices."""

from app.review.fingerprint import create_draft_fingerprint
from app.review.models import RevisionPolicy
from app.services.mock_providers import (
    get_route,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
)
from app.services.planning_service import assemble_travel_plan_from_results
from tests.review.helpers import make_review_requirements


def assemble(policy: RevisionPolicy):
    """Assemble one Tokyo plan from existing provider results and an explicit policy."""

    requirements = make_review_requirements(preferences=["museums"])
    return assemble_travel_plan_from_results(
        requirements=requirements,
        flight_options=search_flights(requirements),
        hotel_options=search_hotels(requirements),
        attractions=search_attractions(requirements),
        weather=get_weather(requirements),
        route=get_route(requirements.origin, requirements.destination),
        revision_policy=policy,
    )


def first_visit(plan) -> str:
    """Read the first structured attraction activity from a plan."""

    return next(
        activity
        for day in plan.daily_itinerary
        for activity in day.activities
        if activity.startswith("Visit ")
    )


def test_budget_revision_selects_cheaper_real_options_and_recalculates_total() -> None:
    """Planner chooses known prices instead of editing the budget or total directly."""

    original = assemble(RevisionPolicy())
    revised = assemble(RevisionPolicy(prefer_lower_cost_options=True))

    assert revised.requirements.budget == original.requirements.budget
    assert revised.flight.price < original.flight.price
    assert revised.hotel.price_per_night < original.hotel.price_per_night
    assert revised.total_cost < original.total_cost
    assert create_draft_fingerprint(revised) != create_draft_fingerprint(original)


def test_pace_revision_reduces_structured_daily_visit_count() -> None:
    """The policy changes activity lists, not only a Markdown sentence."""

    original = assemble(RevisionPolicy())
    revised = assemble(RevisionPolicy(max_activities_per_day=1))

    assert any(
        sum(activity.startswith("Visit ") for activity in day.activities) == 2
        for day in original.daily_itinerary
    )
    assert all(
        sum(activity.startswith("Visit ") for activity in day.activities) <= 1
        for day in revised.daily_itinerary
    )


def test_personalization_revision_moves_matching_attraction_first() -> None:
    """Museum preference deterministically promotes the existing museum result."""

    original = assemble(RevisionPolicy())
    revised = assemble(RevisionPolicy(prioritize_preferences=True))

    assert "Asakusa" in first_visit(original)
    assert "Ueno Museum" in first_visit(revised)
    assert first_visit(revised) != first_visit(original)
    assert "## Applied review feedback" in revised.markdown
