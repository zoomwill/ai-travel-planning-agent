"""Planner node that combines results already produced by P08 subagents."""

from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TravelDataSources,
    TravelPlan,
    TripRequirements,
    WeatherSummary,
)
from app.graphs.state import TravelPlanState
from app.llm.diagnostics import record_deterministic_fallback
from app.llm.errors import LLMError
from app.llm.grounding import (
    GroundingViolation,
    build_grounded_planner_input,
    validate_grounded_decision,
)
from app.llm.protocol import StructuredLLMProvider
from app.observability.logging import log_event
from app.observability.metrics import MetricsRuntime
from app.review.models import RevisionPolicy
from app.search.models import (
    JsonObject,
    SearchKind,
    SearchKindValue,
    dump_model_json,
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


@dataclass(frozen=True, slots=True)
class _PlanningInputs:
    """Validated values shared by deterministic and Qwen Planner paths."""

    requirements: TripRequirements
    revision_policy: RevisionPolicy
    flights: list[FlightOption]
    hotels: list[HotelOption]
    attractions: list[Attraction]
    weather: list[WeatherSummary]
    route: RouteSummary | None
    unavailable: list[str]


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
        "draft_plan": None,
        "travel_plan": None,
        "review_status": "failed",
        "finalization_reason": "critical_search_failure",
        "error": f"critical_search_failed:{names}",
    }


def planner_node(state: TravelPlanState) -> TravelPlanState:
    """Assemble a first or revised draft from existing search and context data."""

    prepared = _prepare_planning_inputs(state)
    if isinstance(prepared, dict):
        return prepared
    return _assemble_plan(state, prepared)


async def qwen_planner_node(
    state: TravelPlanState,
    *,
    provider: StructuredLLMProvider | None,
    allow_deterministic_fallback: bool,
    metrics: MetricsRuntime | None = None,
) -> TravelPlanState:
    """Let Qwen select candidates, then reuse the existing grounded assembler."""

    prepared = _prepare_planning_inputs(state)
    if isinstance(prepared, dict):
        return prepared
    if provider is None:
        error = LLMError("llm_not_configured")
    else:
        try:
            grounded = build_grounded_planner_input(
                requirements=prepared.requirements,
                flights=prepared.flights,
                hotels=prepared.hotels,
                attractions=prepared.attractions,
                retrieved_context=state.get("retrieved_context", []),
                remembered_preferences=state.get("remembered_preferences", []),
                unavailable_searches=prepared.unavailable,
                revision_policy=prepared.revision_policy,
            )
            result = await provider.plan(grounded.prompt)
            selection = validate_grounded_decision(
                result.value,
                grounded,
                requirements=prepared.requirements,
                revision_policy=prepared.revision_policy,
            )
            return _assemble_plan(state, prepared, grounded_selection=selection)
        except LLMError as exc:
            error = exc
            if isinstance(exc, GroundingViolation):
                log_event(
                    "llm_grounding_rejected",
                    "A structured Planner choice failed local grounding.",
                    component="llm",
                    role="planner",
                    outcome="error",
                    error_code=f"{exc.code}:{exc.reason}",
                )
        except Exception:
            error = LLMError("llm_provider_error")

    if allow_deterministic_fallback:
        record_deterministic_fallback(metrics, "planner", error.code)
        return _assemble_plan(state, prepared)
    return {
        "draft_plan": None,
        "travel_plan": None,
        "review_status": "failed",
        "error": error.code,
    }


def _prepare_planning_inputs(
    state: TravelPlanState,
) -> _PlanningInputs | TravelPlanState:
    """Restore validated domain data once for either Planner implementation."""

    if state.get("next_agent") != "planner":
        return {
            "draft_plan": None,
            "travel_plan": None,
            "review_status": "failed",
            "error": state.get("error") or "The Planner Agent was not selected.",
        }
    if state.get("error") is not None:
        return {
            "draft_plan": None,
            "travel_plan": None,
            "review_status": "failed",
            "error": state["error"],
        }

    requirements = state.get("requirements")
    if requirements is None:
        return {
            "draft_plan": None,
            "travel_plan": None,
            "review_status": "failed",
            "error": "Validated trip requirements are required.",
        }

    policy_data = state.get("revision_policy")
    try:
        revision_policy = (
            RevisionPolicy.model_validate(policy_data)
            if policy_data is not None
            else RevisionPolicy()
        )
    except Exception:
        return {
            "draft_plan": None,
            "travel_plan": None,
            "review_status": "failed",
            "error": "revision_failed",
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

    # Historical/injected route JSON has no verified local/intercity scope.
    # Do not supply it to either deterministic or Qwen planning.
    route = None
    if route is None:
        unavailable.append(SearchKind.ROUTE.value)

    reported_error_kinds: set[SearchKindValue] = {
        error["kind"] for error in state.get("tool_errors", [])
    }
    for kind in _NON_CRITICAL_KINDS:
        kind_value = search_kind_value(kind)
        if kind_value in reported_error_kinds and kind_value not in unavailable:
            unavailable.append(kind_value)

    return _PlanningInputs(
        requirements=requirements,
        revision_policy=revision_policy,
        flights=flights,
        hotels=hotels,
        attractions=attractions,
        weather=weather,
        route=route,
        unavailable=unavailable,
    )


def _assemble_plan(
    state: TravelPlanState,
    inputs: _PlanningInputs,
    *,
    grounded_selection: planning_service.GroundedPlanningSelection | None = None,
) -> TravelPlanState:
    """Call the single existing assembly service and map only stable failures."""

    try:
        travel_plan: TravelPlan = planning_service.assemble_travel_plan_from_results(
            requirements=inputs.requirements,
            flight_options=inputs.flights,
            hotel_options=inputs.hotels,
            attractions=inputs.attractions,
            weather=inputs.weather,
            route=inputs.route,
            retrieved_context=state.get("retrieved_context", []),
            remembered_preferences=state.get("remembered_preferences", []),
            unavailable_searches=inputs.unavailable,
            revision_policy=inputs.revision_policy,
            grounded_selection=grounded_selection,
            data_sources=TravelDataSources.model_validate(
                {
                    kind: summary.get("source", "demo")
                    for kind, summary in state.get("search_summary", {}).items()
                }
            ),
        )
    except planning_service.PlanningServiceError:
        error_code = (
            "revision_failed" if state.get("review_round", 0) > 0 else "plan_assembly_failed"
        )
        return {
            "draft_plan": None,
            "travel_plan": None,
            "review_status": "failed",
            "error": error_code,
        }

    return {
        "draft_plan": dump_model_json(travel_plan),
        "travel_plan": None,
        "applied_feedback": inputs.revision_policy.applied_feedback(),
        "error": None,
    }


def route_after_planner(state: TravelPlanState) -> Literal["reviewer", "__end__"]:
    """Skip Reviewer whenever Planner could not produce a valid draft."""

    if state.get("draft_plan") is not None and state.get("error") is None:
        return "reviewer"
    return "__end__"
