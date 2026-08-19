"""HTTP boundary for the deterministic Phase P05 LangGraph runtime."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from langgraph.errors import GraphRecursionError

from app.domain.models import TravelPlan, TripRequirements
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import TravelPlanningGraph
from app.graphs.state import TravelPlanState
from app.observability.instrumentation import invoke_graph_once

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.post(
    "/plans",
    response_model=TravelPlan,
    status_code=status.HTTP_200_OK,
    summary="Create a deterministic plan through LangGraph",
)
async def create_agent_plan(request: Request, requirements: TripRequirements) -> TravelPlan:
    """Run validated requirements through Router, Retriever, and Planner nodes."""

    preferences = ", ".join(requirements.preferences) or "none"

    initial_state: TravelPlanState = {
        "user_request": (
            f"Plan a trip from {requirements.origin} to {requirements.destination}. "
            f"Preferences: {preferences}."
        ),
        "requirements": requirements,
        "search_backend_mode": request.app.state.settings.travel_search_backend_mode,
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

    try:
        graph = cast(TravelPlanningGraph, request.app.state.travel_planning_graph)
        final_state = cast(
            TravelPlanState,
            await invoke_graph_once(
                lambda: graph.ainvoke(
                    initial_state,
                    config={
                        "recursion_limit": request.app.state.settings.graph_recursion_limit,
                    },
                    context=TravelRuntimeContext(user_id="anonymous"),
                ),
                metrics=request.app.state.metrics,
                backend=request.app.state.settings.travel_search_backend_mode,
            ),
        )
    except GraphRecursionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "graph_recursion_limit_reached",
                "message": "The agent graph reached its configured safety limit.",
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_runtime_unavailable",
                "message": "The agent planning runtime could not complete the request.",
            },
        ) from exc

    travel_plan = final_state.get("travel_plan")
    graph_error = final_state.get("error")
    if graph_error is not None:
        error_code = (
            "critical_search_failed"
            if graph_error.startswith("critical_search_failed:")
            else graph_error
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": error_code,
                "message": "The agent planning runtime ended with a safe error.",
            },
        )
    if travel_plan is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=final_state.get("error") or "The Planner Agent did not return a plan.",
        )
    return travel_plan
