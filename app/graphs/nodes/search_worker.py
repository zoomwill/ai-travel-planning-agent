"""Generic worker executed once for each specialized search subagent."""

from pydantic import BaseModel

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TripRequirements,
    WeatherSummary,
)
from app.graphs.state import TravelPlanState
from app.search.backend import SearchBackend
from app.search.models import (
    SearchErrorEnvelope,
    SearchKind,
    SearchResultEnvelope,
    SearchWorkerInput,
    create_request_fingerprint,
    dump_model_json,
)


class _EmptySearchResultError(RuntimeError):
    """Internal signal converted into a safe worker error envelope."""


class _InvalidSearchResultError(RuntimeError):
    """Internal signal for a backend result that violates its typed contract."""


async def _call_backend(
    kind: SearchKind,
    requirements: TripRequirements,
    backend: SearchBackend,
) -> list[BaseModel]:
    """Call exactly one backend method for the dispatched search kind."""

    if kind is SearchKind.FLIGHTS:
        flight_results = await backend.search_flights(requirements)
        if not all(isinstance(item, FlightOption) for item in flight_results):
            raise _InvalidSearchResultError
        return list(flight_results)
    if kind is SearchKind.HOTELS:
        hotel_results = await backend.search_hotels(requirements)
        if not all(isinstance(item, HotelOption) for item in hotel_results):
            raise _InvalidSearchResultError
        return list(hotel_results)
    if kind is SearchKind.ATTRACTIONS:
        attraction_results = await backend.search_attractions(requirements)
        if not all(isinstance(item, Attraction) for item in attraction_results):
            raise _InvalidSearchResultError
        return list(attraction_results)
    if kind is SearchKind.WEATHER:
        weather_results = await backend.get_weather(requirements)
        if not all(isinstance(item, WeatherSummary) for item in weather_results):
            raise _InvalidSearchResultError
        return list(weather_results)

    result = await backend.get_route(requirements.origin, requirements.destination)
    if not isinstance(result, RouteSummary):
        raise _InvalidSearchResultError
    return [result]


def _error_type(exception: Exception) -> str:
    """Map internal exception classes to stable machine-readable categories."""

    if isinstance(exception, _EmptySearchResultError):
        return "empty_result"
    if isinstance(exception, (_InvalidSearchResultError, ValueError)):
        return "invalid_result"
    return "provider_error"


async def search_worker_node(
    worker_input: SearchWorkerInput,
    *,
    backend: SearchBackend,
) -> TravelPlanState:
    """Execute one search and return only a result or safe tool error update."""

    task = worker_input["search_task"]
    kind = SearchKind(task["kind"])
    try:
        requirements = TripRequirements.model_validate(worker_input["requirements_data"])
        if task["request_fingerprint"] != create_request_fingerprint(requirements):
            raise ValueError("task fingerprint does not match requirements")
        models = await _call_backend(kind, requirements, backend)
        if not models:
            raise _EmptySearchResultError
    except Exception as exc:
        error = SearchErrorEnvelope(
            task_id=task["task_id"],
            kind=task["kind"],
            error_type=_error_type(exc),
            safe_message=f"The {kind.value} search is unavailable.",
            recoverable=not isinstance(exc, (ValueError, _InvalidSearchResultError)),
        )
        return {"tool_errors": [error]}

    result = SearchResultEnvelope(
        task_id=task["task_id"],
        kind=task["kind"],
        status="ok",
        data=[dump_model_json(model) for model in models],
    )
    return {"search_results": [result]}
