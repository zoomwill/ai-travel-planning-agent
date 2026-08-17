"""HTTP boundaries for durable graph threads and explicit user memory."""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import StateSnapshot

from app.core.persistence import PersistenceResources
from app.domain.models import TravelPlan
from app.graphs.context import TravelRuntimeContext
from app.graphs.state import TravelPlanState
from app.memory.models import PreferenceMemory
from app.memory.preferences import delete_user_preference, list_user_preferences
from app.review.models import PlanReview
from app.schemas.persistence import (
    ThreadHistoryItem,
    ThreadHistoryResponse,
    ThreadPlanRequest,
    ThreadPlanResponse,
    ThreadStateResponse,
)
from app.streaming.models import StreamHeartbeat
from app.streaming.service import TravelPlanStream

router = APIRouter(tags=["persistence"])

_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class _PreparedPlanStream:
    """Validated dependencies ready before FastAPI commits SSE headers."""

    stream: TravelPlanStream


def _raise_api_error(http_status: int, code: str, message: str) -> NoReturn:
    """Raise a stable error without including an underlying exception or DSN."""

    raise HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


def _validate_thread_id(thread_id: str) -> str:
    """Accept bounded identifiers containing only URL- and log-safe characters."""

    if _THREAD_ID_PATTERN.fullmatch(thread_id) is None:
        _raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_thread_id",
            "thread_id must be 1-128 safe characters: letters, numbers, "
            "dot, underscore, or hyphen.",
        )
    return thread_id


def _validate_user_id(user_id: str) -> str:
    """Accept a bounded local user identifier without pretending it is authentication."""

    if _USER_ID_PATTERN.fullmatch(user_id) is None:
        _raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_user_id",
            "user_id must be 1-64 safe characters: letters, numbers, dot, underscore, or hyphen.",
        )
    return user_id


def _get_persistence(request: Request) -> PersistenceResources:
    """Read application-owned persistence or return a stable initialization error."""

    try:
        return cast(PersistenceResources, request.app.state.persistence)
    except AttributeError:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "persistence_not_initialized",
            "The persistence runtime is not initialized.",
        )


def _thread_config(
    thread_id: str,
    *,
    recursion_limit: int | None = None,
) -> RunnableConfig:
    """Build the LangGraph configurable section used as the checkpoint key."""

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    if recursion_limit is not None:
        config["recursion_limit"] = recursion_limit
    return config


def _make_initial_state(payload: ThreadPlanRequest) -> TravelPlanState:
    """Build a complete beginner-readable state for a persistent graph invocation."""

    preferences = ", ".join(payload.requirements.preferences) or "none"
    return {
        "user_request": (
            f"Plan a trip from {payload.requirements.origin} "
            f"to {payload.requirements.destination}. Preferences: {preferences}."
        ),
        "requirements": payload.requirements,
        "search_backend_mode": "direct",
        "next_agent": None,
        "remembered_preferences": [],
        "retrieved_context": [],
        "retrieval_query_variants": [],
        "retrieval_parent_ids": [],
        "retrieval_diagnostics": None,
        "retrieval_error": None,
        "search_tasks": [],
        "search_results": [],
        "tool_errors": [],
        "search_summary": {},
        "draft_plan": None,
        "current_review": None,
        "review_history": [],
        "review_round": 0,
        "critique": None,
        "revision_policy": None,
        "applied_feedback": [],
        "review_status": "pending",
        "finalization_reason": None,
        "travel_plan": None,
        "error": None,
    }


def _state_status(values: dict[str, Any], next_nodes: tuple[str, ...] = ()) -> str:
    """Translate graph values into a small public status vocabulary."""

    if values.get("error"):
        return "error"
    if values.get("travel_plan") is not None:
        return "complete"
    if next_nodes:
        return "running"
    return "empty"


def _snapshot_checkpoint_id(snapshot: StateSnapshot) -> str:
    """Read a checkpoint ID without exposing the rest of its runnable config."""

    configurable = snapshot.config.get("configurable", {})
    checkpoint_id = configurable.get("checkpoint_id", "")
    return str(checkpoint_id)


async def _prepare_plan_stream(
    thread_id: str,
    payload: ThreadPlanRequest,
    request: Request,
) -> _PreparedPlanStream:
    """Validate the complete persistent request before opening an SSE response."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = _validate_user_id(payload.user_id)
    persistence = _get_persistence(request)
    settings = request.app.state.settings
    backend_mode = settings.travel_search_backend_mode
    if backend_mode == "mcp":
        try:
            resources = request.app.state.resources
            runtime = resources.mcp_runtime
            ready = runtime is not None and await asyncio.wait_for(
                runtime.is_ready(),
                timeout=settings.mcp_discovery_timeout_seconds,
            )
        except Exception:
            ready = False
        if not ready:
            _raise_api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "stream_backend_unavailable",
                "The configured MCP travel-search backend is not ready.",
            )

    initial_state = _make_initial_state(payload)
    initial_state["search_backend_mode"] = backend_mode
    context = TravelRuntimeContext(
        user_id=validated_user_id,
        preferences_to_remember=tuple(payload.remember_preferences),
    )
    return _PreparedPlanStream(
        stream=TravelPlanStream(
            graph=persistence.graph,
            initial_state=initial_state,
            config=_thread_config(
                validated_thread_id,
                recursion_limit=settings.graph_recursion_limit,
            ),
            context=context,
            thread_id=validated_thread_id,
            backend_mode=backend_mode,
            heartbeat_seconds=settings.sse_heartbeat_seconds,
            queue_maxsize=settings.sse_queue_maxsize,
        )
    )


@router.post(
    "/api/v1/agents/threads/{thread_id}/plans/stream",
    response_class=EventSourceResponse,
    responses={503: {"description": "Persistence or configured search backend unavailable"}},
)
async def stream_thread_plan(
    prepared: Annotated[_PreparedPlanStream, Depends(_prepare_plan_stream)],
) -> AsyncIterator[ServerSentEvent]:
    """Stream one persistent graph execution as typed SSE business events."""

    async for item in prepared.stream.stream():
        if isinstance(item, StreamHeartbeat):
            yield ServerSentEvent(comment=item.comment)
            continue
        event = item
        yield ServerSentEvent(
            id=str(event.event_id),
            event=event.event_type.value,
            data=event.model_dump(mode="json"),
        )


@router.post(
    "/api/v1/agents/threads/{thread_id}/plans",
    response_model=ThreadPlanResponse,
)
async def create_thread_plan(
    thread_id: str,
    payload: ThreadPlanRequest,
    request: Request,
) -> ThreadPlanResponse:
    """Run one plan with durable checkpoints and explicit user memory."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = _validate_user_id(payload.user_id)
    persistence = _get_persistence(request)
    initial_state = _make_initial_state(payload)
    initial_state["search_backend_mode"] = request.app.state.settings.travel_search_backend_mode
    context = TravelRuntimeContext(
        user_id=validated_user_id,
        preferences_to_remember=tuple(payload.remember_preferences),
    )
    try:
        result = await persistence.graph.ainvoke(
            initial_state,
            config=_thread_config(
                validated_thread_id,
                recursion_limit=request.app.state.settings.graph_recursion_limit,
            ),
            context=context,
        )
    except GraphRecursionError:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "graph_recursion_limit_reached",
            "The persistent graph reached its configured safety limit.",
        )
    except Exception:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "checkpoint_unavailable",
            "The persistent graph could not complete the request.",
        )

    final_state = cast(TravelPlanState, result)
    error = final_state.get("error")
    if error in {"store_unavailable", "checkpoint_unavailable"}:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error,
            "The persistence runtime could not complete the request.",
        )
    if error is not None and error.startswith("critical_search_failed:"):
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "critical_search_failed",
            "Required flight or hotel search data is unavailable.",
        )
    if error == "plan_assembly_failed":
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "plan_assembly_failed",
            "The validated search results could not be assembled into a plan.",
        )
    if error in {
        "reviewer_failed",
        "review_output_invalid",
        "revision_failed",
        "finalization_failed",
    }:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error,
            "The quality review workflow could not safely complete the request.",
        )
    travel_plan = final_state.get("travel_plan")
    if travel_plan is None:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "checkpoint_unavailable",
            "The persistent Planner Agent did not return a plan.",
        )
    review_summary = _validated_review(final_state.get("current_review"))
    return ThreadPlanResponse(
        thread_id=validated_thread_id,
        user_id=validated_user_id,
        search_backend_mode=final_state.get("search_backend_mode", "direct"),
        travel_plan=travel_plan,
        remembered_preferences=final_state.get("remembered_preferences", []),
        search_summary=final_state.get("search_summary", {}),
        tool_errors=final_state.get("tool_errors", []),
        review_status=final_state.get("review_status", "failed"),
        review_rounds=final_state.get("review_round", 0),
        final_score=(review_summary.scores.overall_score if review_summary is not None else None),
        finalization_reason=final_state.get("finalization_reason"),
        review_summary=review_summary,
        retrieval_query_variants=final_state.get("retrieval_query_variants", []),
        retrieval_parent_ids=final_state.get("retrieval_parent_ids", []),
        retrieval_diagnostics=final_state.get("retrieval_diagnostics"),
        retrieval_error=final_state.get("retrieval_error"),
    )


@router.get(
    "/api/v1/agents/threads/{thread_id}/state",
    response_model=ThreadStateResponse,
)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    """Return a safe projection of the latest durable checkpoint."""

    validated_thread_id = _validate_thread_id(thread_id)
    persistence = _get_persistence(request)
    try:
        snapshot = await persistence.graph.aget_state(_thread_config(validated_thread_id))
    except Exception:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "checkpoint_unavailable",
            "The latest checkpoint could not be read.",
        )
    values = cast(dict[str, Any], snapshot.values)
    if not values:
        _raise_api_error(
            status.HTTP_404_NOT_FOUND,
            "checkpoint_unavailable",
            "No checkpoint exists for this thread.",
        )
    travel_plan_value = values.get("travel_plan")
    travel_plan = (
        TravelPlan.model_validate(travel_plan_value) if travel_plan_value is not None else None
    )
    review_summary = _validated_review(values.get("current_review"))
    return ThreadStateResponse(
        thread_id=validated_thread_id,
        status=cast(Any, _state_status(values, snapshot.next)),
        search_backend_mode=values.get("search_backend_mode", "direct"),
        user_request=values.get("user_request"),
        next_agent=values.get("next_agent"),
        remembered_preferences=values.get("remembered_preferences", []),
        search_summary=values.get("search_summary", {}),
        search_result_count=len(values.get("search_results", [])),
        tool_error_count=len(values.get("tool_errors", [])),
        review_status=values.get("review_status", "pending"),
        review_round=values.get("review_round", 0),
        final_score=(review_summary.scores.overall_score if review_summary is not None else None),
        finalization_reason=values.get("finalization_reason"),
        draft_present=values.get("draft_plan") is not None,
        review_history_count=len(values.get("review_history", [])),
        retrieval_query_variant_count=len(values.get("retrieval_query_variants", [])),
        retrieval_parent_ids=values.get("retrieval_parent_ids", []),
        retrieval_diagnostics=values.get("retrieval_diagnostics"),
        retrieval_error=values.get("retrieval_error"),
        travel_plan=travel_plan,
        error=values.get("error"),
    )


@router.get(
    "/api/v1/agents/threads/{thread_id}/history",
    response_model=ThreadHistoryResponse,
)
async def get_thread_history(
    thread_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> ThreadHistoryResponse:
    """Return bounded, newest-first checkpoint summaries."""

    validated_thread_id = _validate_thread_id(thread_id)
    persistence = _get_persistence(request)
    checkpoints: list[ThreadHistoryItem] = []
    try:
        async for snapshot in persistence.graph.aget_state_history(
            _thread_config(validated_thread_id),
            limit=limit,
        ):
            values = cast(dict[str, Any], snapshot.values)
            checkpoints.append(
                ThreadHistoryItem(
                    checkpoint_id=_snapshot_checkpoint_id(snapshot),
                    created_at=snapshot.created_at,
                    next=list(snapshot.next),
                    tasks=[task.name for task in snapshot.tasks],
                    status=cast(Any, _state_status(values, snapshot.next)),
                )
            )
    except Exception:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "checkpoint_unavailable",
            "Checkpoint history could not be read.",
        )
    return ThreadHistoryResponse(
        thread_id=validated_thread_id,
        checkpoints=checkpoints,
    )


def _validated_review(value: object) -> PlanReview | None:
    """Validate JSON review state before including its safe public projection."""

    if value is None:
        return None
    try:
        return PlanReview.model_validate(value)
    except Exception:
        return None


@router.get(
    "/api/v1/users/{user_id}/preferences",
    response_model=list[PreferenceMemory],
)
async def get_user_preferences(user_id: str, request: Request) -> list[PreferenceMemory]:
    """List only the preferences in the requested user's namespace."""

    validated_user_id = _validate_user_id(user_id)
    persistence = _get_persistence(request)
    try:
        return await list_user_preferences(persistence.store, validated_user_id)
    except Exception:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "store_unavailable",
            "User preferences could not be read.",
        )


@router.delete(
    "/api/v1/users/{user_id}/preferences/{preference_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_preference(
    user_id: str,
    preference_id: str,
    request: Request,
) -> Response:
    """Delete one preference without touching the rest of the namespace."""

    validated_user_id = _validate_user_id(user_id)
    persistence = _get_persistence(request)
    try:
        deleted = await delete_user_preference(
            persistence.store,
            user_id=validated_user_id,
            preference_id=preference_id,
        )
    except Exception:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "store_unavailable",
            "The preference could not be deleted.",
        )
    if not deleted:
        _raise_api_error(
            status.HTTP_404_NOT_FOUND,
            "preference_not_found",
            "The requested preference does not exist for this user.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
