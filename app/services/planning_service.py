"""Deterministically assemble a travel plan from the Phase P03 providers."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final

from app.domain.models import (
    Attraction,
    DailyItinerary,
    FlightOption,
    HotelOption,
    RouteSummary,
    TravelPlan,
    TripRequirements,
    WeatherSummary,
)
from app.review.models import RevisionPolicy
from app.services.mock_providers import (
    get_route,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
)

FlightSearch = Callable[[TripRequirements], list[FlightOption]]
HotelSearch = Callable[[TripRequirements], list[HotelOption]]
AttractionSearch = Callable[[TripRequirements], list[Attraction]]
WeatherLookup = Callable[[TripRequirements], list[WeatherSummary]]
RouteLookup = Callable[[str, str], RouteSummary]


@dataclass(frozen=True, slots=True)
class PlanningProviders:
    """Group provider callables so tests and future adapters can replace them."""

    search_flights: FlightSearch
    search_hotels: HotelSearch
    search_attractions: AttractionSearch
    get_weather: WeatherLookup
    get_route: RouteLookup


MOCK_PLANNING_PROVIDERS: Final = PlanningProviders(
    search_flights=search_flights,
    search_hotels=search_hotels,
    search_attractions=search_attractions,
    get_weather=get_weather,
    get_route=get_route,
)


class PlanningServiceError(RuntimeError):
    """Report which safe planning stage failed without exposing private details."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"mock travel planning failed during {stage}")


def create_mock_travel_plan(
    requirements: TripRequirements,
    providers: PlanningProviders = MOCK_PLANNING_PROVIDERS,
) -> TravelPlan:
    """Build one repeatable plan from validated requirements and mock data."""

    flights = _search_flights(requirements, providers)
    hotels = _search_hotels(requirements, providers)
    attractions = _search_attractions(requirements, providers)
    weather = _get_weather(requirements, providers)

    if not flights:
        raise PlanningServiceError("flight selection")
    if not hotels:
        raise PlanningServiceError("hotel selection")
    if not attractions:
        raise PlanningServiceError("attraction selection")
    if not weather:
        raise PlanningServiceError("weather selection")

    route = _get_route(requirements, providers)
    return assemble_travel_plan_from_results(
        requirements=requirements,
        flight_options=flights,
        hotel_options=hotels,
        attractions=attractions,
        weather=weather,
        route=route,
    )


def assemble_travel_plan_from_results(
    *,
    requirements: TripRequirements,
    flight_options: list[FlightOption],
    hotel_options: list[HotelOption],
    attractions: list[Attraction],
    weather: list[WeatherSummary],
    route: RouteSummary | None,
    retrieved_context: Sequence[str] = (),
    remembered_preferences: Sequence[str] = (),
    unavailable_searches: Sequence[str] = (),
    revision_policy: RevisionPolicy | None = None,
) -> TravelPlan:
    """Combine validated search results without calling any provider."""

    if not flight_options:
        raise PlanningServiceError("flight selection")
    if not hotel_options:
        raise PlanningServiceError("hotel selection")

    policy = revision_policy or RevisionPolicy()
    flight = _select_flight(flight_options, policy)
    hotel = _select_hotel(hotel_options, policy)
    planned_attractions = _select_attractions(
        attractions,
        policy=policy,
        preferences=[*requirements.preferences, *remembered_preferences],
    )

    try:
        daily_itinerary = _build_daily_itinerary(
            requirements=requirements,
            hotel=hotel,
            attractions=planned_attractions,
            weather=weather,
            route=route,
            flight=flight,
            max_activities_per_day=policy.max_activities_per_day,
        )
        hotel_cost = hotel.price_per_night * Decimal(len(daily_itinerary))
        activity_cost = sum(
            (day.estimated_cost for day in daily_itinerary),
            start=Decimal("0.00"),
        )
        total_cost = flight.price + hotel_cost + activity_cost
        budget_warning = _build_budget_warning(requirements, total_cost)
        plan = TravelPlan(
            requirements=requirements,
            flight=flight,
            hotel=hotel,
            daily_itinerary=daily_itinerary,
            total_cost=total_cost,
            currency=requirements.currency,
            budget_warning=budget_warning,
        )
        plan = plan.model_copy(update={"markdown": _render_markdown(plan)})
        contextual_plan = _add_context_sections(
            plan,
            retrieved_context=retrieved_context,
            remembered_preferences=remembered_preferences,
            unavailable_searches=unavailable_searches,
        )
        return _add_revision_section(contextual_plan, policy)
    except PlanningServiceError:
        raise
    except Exception as exc:
        raise PlanningServiceError("plan assembly") from exc


def _search_flights(
    requirements: TripRequirements,
    providers: PlanningProviders,
) -> list[FlightOption]:
    """Call the configured flight provider with a safe failure boundary."""

    try:
        return providers.search_flights(requirements)
    except Exception as exc:
        raise PlanningServiceError("flight search") from exc


def _search_hotels(
    requirements: TripRequirements,
    providers: PlanningProviders,
) -> list[HotelOption]:
    """Call the configured hotel provider with a safe failure boundary."""

    try:
        return providers.search_hotels(requirements)
    except Exception as exc:
        raise PlanningServiceError("hotel search") from exc


def _search_attractions(
    requirements: TripRequirements,
    providers: PlanningProviders,
) -> list[Attraction]:
    """Call the configured attraction provider with a safe failure boundary."""

    try:
        return providers.search_attractions(requirements)
    except Exception as exc:
        raise PlanningServiceError("attraction search") from exc


def _get_weather(
    requirements: TripRequirements,
    providers: PlanningProviders,
) -> list[WeatherSummary]:
    """Call the configured weather provider with a safe failure boundary."""

    try:
        return providers.get_weather(requirements)
    except Exception as exc:
        raise PlanningServiceError("weather lookup") from exc


def _get_route(
    requirements: TripRequirements,
    providers: PlanningProviders,
) -> RouteSummary:
    """Look up the independent trip origin-to-destination route."""

    try:
        return providers.get_route(requirements.origin, requirements.destination)
    except Exception as exc:
        raise PlanningServiceError("route lookup") from exc


def _build_daily_itinerary(
    *,
    requirements: TripRequirements,
    hotel: HotelOption,
    attractions: list[Attraction],
    weather: list[WeatherSummary],
    route: RouteSummary | None,
    flight: FlightOption,
    max_activities_per_day: int | None = None,
) -> list[DailyItinerary]:
    """Create one day entry per inclusive trip date using repeatable rules."""

    weather_by_date = {summary.date: summary for summary in weather}
    day_count = (requirements.end_date - requirements.start_date).days + 1
    traveler_count = Decimal(requirements.travelers)
    attraction_index = 0
    itinerary: list[DailyItinerary] = []

    for offset in range(day_count):
        current_date = requirements.start_date + timedelta(days=offset)
        daily_weather = weather_by_date.get(current_date)
        visit_count = 1 if offset == 0 else 2
        if max_activities_per_day is not None:
            visit_count = min(visit_count, max_activities_per_day)
        daily_attractions: list[Attraction] = []
        if attractions:
            daily_attractions = [
                attractions[(attraction_index + index) % len(attractions)]
                for index in range(visit_count)
            ]
            attraction_index += visit_count

        activities: list[str] = []
        if offset == 0:
            activities.extend(
                [
                    (f"Arrive in {requirements.destination} on flight {flight.flight_number}"),
                    f"Check in at {hotel.name}",
                ]
            )
            if route is None:
                activities.append("Route information unavailable.")
            else:
                activities.append(
                    f"Route estimate from {route.origin} to {route.destination} by "
                    f"{route.transport_mode.value} ({route.duration_minutes} minutes)"
                )
        activities.extend(
            f"Visit {attraction.name} ({attraction.opening_hours})"
            for attraction in daily_attractions
        )
        if not daily_attractions:
            activities.append("Attraction information unavailable.")
        if daily_weather is None:
            activities.append("Weather information unavailable.")
            day_condition = "flexible schedule"
        else:
            activities.append(
                f"Weather: {daily_weather.condition}, "
                f"{daily_weather.temperature_celsius:.1f} C, "
                f"{daily_weather.rain_probability}% rain chance"
            )
            day_condition = daily_weather.condition

        daily_cost = (
            sum(
                (attraction.estimated_cost for attraction in daily_attractions),
                start=Decimal("0.00"),
            )
            * traveler_count
        )
        itinerary.append(
            DailyItinerary(
                day_number=offset + 1,
                date=current_date,
                title=f"{requirements.destination} day {offset + 1}: {day_condition}",
                activities=activities,
                estimated_cost=daily_cost,
                currency=requirements.currency,
            )
        )

    return itinerary


def _select_flight(
    flight_options: list[FlightOption],
    policy: RevisionPolicy,
) -> FlightOption:
    """Preserve P04 selection unless review explicitly requests lower cost."""

    if not policy.prefer_lower_cost_options:
        return flight_options[0]
    return min(
        flight_options,
        key=lambda option: (option.price, option.duration_minutes, option.flight_number),
    )


def _select_hotel(
    hotel_options: list[HotelOption],
    policy: RevisionPolicy,
) -> HotelOption:
    """Preserve highest-rating selection unless review requests lower cost."""

    if not policy.prefer_lower_cost_options:
        return max(hotel_options, key=lambda option: option.rating)
    return min(
        hotel_options,
        key=lambda option: (option.price_per_night, -option.rating, option.name),
    )


def _select_attractions(
    attractions: list[Attraction],
    *,
    policy: RevisionPolicy,
    preferences: Sequence[str],
) -> list[Attraction]:
    """Apply preference ordering and optional-cost reduction to known attractions."""

    selected = list(attractions)
    if policy.prioritize_preferences:
        ranked = sorted(
            enumerate(selected),
            key=lambda pair: (
                -_attraction_preference_score(pair[1], preferences),
                pair[0],
            ),
        )
        selected = [attraction for _, attraction in ranked]
    if policy.prefer_lower_cost_options and selected:
        minimum_cost = min(attraction.estimated_cost for attraction in selected)
        selected = [
            attraction for attraction in selected if attraction.estimated_cost == minimum_cost
        ]
    return selected


def _attraction_preference_score(
    attraction: Attraction,
    preferences: Sequence[str],
) -> int:
    """Rank known attraction text with a small documented semantic vocabulary."""

    text = " ".join([attraction.name, attraction.category, attraction.description]).casefold()
    preference_text = " ".join(preferences).casefold()
    score = sum(token in text for token in preference_text.split())

    semantic_categories: dict[str, tuple[str, ...]] = {
        "photography": ("viewpoint", "landmark", "park", "walk"),
        "photo": ("viewpoint", "landmark", "park", "walk"),
        "museum": ("museum",),
        "museums": ("museum",),
        "quiet": ("park", "garden", "walk"),
        "culture": ("culture", "museum", "heritage"),
        "history": ("culture", "museum", "heritage", "historic"),
    }
    for preference_token, attraction_tokens in semantic_categories.items():
        if preference_token in preference_text:
            score += sum(token in text for token in attraction_tokens)
    return score


def _build_budget_warning(
    requirements: TripRequirements,
    total_cost: Decimal,
) -> str | None:
    """Return a warning instead of rejecting a valid over-budget plan."""

    if total_cost <= requirements.budget:
        return None
    difference = total_cost - requirements.budget
    return (
        f"Estimated total {total_cost:.2f} {requirements.currency.value} exceeds "
        f"the budget by {difference:.2f} {requirements.currency.value}."
    )


def _render_markdown(plan: TravelPlan) -> str:
    """Render the structured plan as beginner-readable Markdown."""

    lines = [
        f"# Mock travel plan: {plan.requirements.origin} to {plan.requirements.destination}",
        "",
        f"- Flight: {plan.flight.airline} {plan.flight.flight_number}",
        f"- Hotel: {plan.hotel.name}",
        f"- Estimated total: {plan.total_cost:.2f} {plan.currency.value}",
    ]
    if plan.budget_warning is not None:
        lines.extend(["", f"> {plan.budget_warning}"])

    for day in plan.daily_itinerary:
        lines.extend(["", f"## Day {day.day_number} — {day.date.isoformat()}"])
        lines.extend(f"- {activity}" for activity in day.activities)

    return "\n".join(lines)


def _add_context_sections(
    plan: TravelPlan,
    *,
    retrieved_context: Sequence[str],
    remembered_preferences: Sequence[str],
    unavailable_searches: Sequence[str],
) -> TravelPlan:
    """Append graph context and explicit degraded-plan notices to Markdown."""

    sections: list[str] = []
    context_lines = [context.strip() for context in retrieved_context if context.strip()]
    if context_lines:
        sections.extend(["## Retrieved travel knowledge", *(f"- {line}" for line in context_lines)])

    preference_lines = [
        preference.strip() for preference in remembered_preferences if preference.strip()
    ]
    if preference_lines:
        sections.extend(["## Remembered preferences", *(f"- {line}" for line in preference_lines)])

    unavailable = sorted(set(unavailable_searches))
    if unavailable:
        sections.extend(
            [
                "## Search limitations",
                *(
                    f"- {kind} information is unavailable; this plan does not invent it."
                    for kind in unavailable
                ),
            ]
        )

    if not sections:
        return plan
    return plan.model_copy(update={"markdown": "\n\n".join([plan.markdown, "\n".join(sections)])})


def _add_revision_section(plan: TravelPlan, policy: RevisionPolicy) -> TravelPlan:
    """Describe executable policy changes after structured fields have changed."""

    applied_feedback = policy.applied_feedback()
    if not applied_feedback:
        return plan
    section = "\n".join(["## Applied review feedback", *(f"- {item}" for item in applied_feedback)])
    return plan.model_copy(update={"markdown": "\n\n".join([plan.markdown, section])})
