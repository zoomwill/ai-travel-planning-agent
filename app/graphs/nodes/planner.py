"""Planner node that combines results already produced by P08 subagents."""

from typing import TypeVar

from pydantic import BaseModel

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TravelPlan,
    WeatherSummary,
)
from app.graphs.state import TravelPlanState
from app.search.models import (
    JsonObject,
    SearchKind,
    SearchKindValue,
    search_kind_value,
)
from app.services import planning_service

ModelT = TypeVar("ModelT", bound=BaseModel)
_CRITICAL_KINDS = (SearchKind.FLIGHTS, SearchKind.HOTELS)
_NON_CRITICAL_KINDS = (
    SearchKind.ATTRACTIONS,
    SearchKind.WEATHER,
    SearchKind.ROUTE,
)


def _validate_models(model_type: type[ModelT], data: list[JsonObject]) -> list[ModelT]:
    """Restore JSON-safe checkpoint data to validated Pydantic domain models."""

    return [model_type.model_validate(item) for item in data]


def _available_result_data(
    state: TravelPlanState,
    kind: SearchKind,
) -> list[JsonObject]:
    """Return successful data only when summary and tool errors agree it is usable."""

    kind_value = search_kind_value(kind)
    summary = state.get("search_summary", {}).get(kind_value)
    failed_kinds = {error["kind"] for error in state.get("tool_errors", [])}
    if summary is None or summary["status"] != "ok" or kind_value in failed_kinds:
        return []
    for result in state.get("search_results", []):
        if result["kind"] == kind_value:
            return result["data"]
    return []


def _critical_error(kinds: list[SearchKind]) -> TravelPlanState:
    """Return a stable critical-search failure without provider exception details."""

    names = ",".join(kind.value for kind in kinds)
    return {
        "travel_plan": None,
        "error": f"critical_search_failed:{names}",
    }


def planner_node(state: TravelPlanState) -> TravelPlanState:
    """Validate parallel results and assemble a complete or degraded travel plan."""

    if state.get("next_agent") != "planner":
        return {
            "travel_plan": None,
            "error": state.get("error") or "The Planner Agent was not selected.",
        }
    if state.get("error") is not None:
        return {"travel_plan": None, "error": state["error"]}

    requirements = state.get("requirements")
    if requirements is None:
        return {
            "travel_plan": None,
            "error": "Validated trip requirements are required.",
        }

    missing_critical = [kind for kind in _CRITICAL_KINDS if not _available_result_data(state, kind)]
    if missing_critical:
        return _critical_error(missing_critical)

    try:
        flights = _validate_models(
            FlightOption,
            _available_result_data(state, SearchKind.FLIGHTS),
        )
        hotels = _validate_models(
            HotelOption,
            _available_result_data(state, SearchKind.HOTELS),
        )
    except Exception:
        return _critical_error(list(_CRITICAL_KINDS))

    unavailable: list[str] = []
    try:
        attractions = _validate_models(
            Attraction,
            _available_result_data(state, SearchKind.ATTRACTIONS),
        )
    except Exception:
        attractions = []
    if not attractions:
        unavailable.append(SearchKind.ATTRACTIONS.value)

    try:
        weather = _validate_models(
            WeatherSummary,
            _available_result_data(state, SearchKind.WEATHER),
        )
    except Exception:
        weather = []
    if not weather:
        unavailable.append(SearchKind.WEATHER.value)

    try:
        routes = _validate_models(
            RouteSummary,
            _available_result_data(state, SearchKind.ROUTE),
        )
    except Exception:
        routes = []
    route = routes[0] if routes else None
    if route is None:
        unavailable.append(SearchKind.ROUTE.value)

    reported_error_kinds: set[SearchKindValue] = {
        error["kind"] for error in state.get("tool_errors", [])
    }
    for kind in _NON_CRITICAL_KINDS:
        kind_value = search_kind_value(kind)
        if kind_value in reported_error_kinds and kind_value not in unavailable:
            unavailable.append(kind_value)

    try:
        travel_plan: TravelPlan = planning_service.assemble_travel_plan_from_results(
            requirements=requirements,
            flight_options=flights,
            hotel_options=hotels,
            attractions=attractions,
            weather=weather,
            route=route,
            retrieved_context=state.get("retrieved_context", []),
            remembered_preferences=state.get("remembered_preferences", []),
            unavailable_searches=unavailable,
        )
    except planning_service.PlanningServiceError:
        return {"travel_plan": None, "error": "plan_assembly_failed"}

    return {"travel_plan": travel_plan, "error": None}
