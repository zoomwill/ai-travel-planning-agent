"""HTTP boundary for the deterministic Phase P05 LangGraph runtime."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from langgraph.errors import GraphRecursionError

from app.domain.models import TravelPlan, TripRequirements
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import TravelPlanningGraph
from app.graphs.state import TravelPlanState

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
        "next_agent": None,
        "remembered_preferences": [],
        "retrieved_context": [],
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
            await graph.ainvoke(
                initial_state,
                config={
                    "recursion_limit": request.app.state.settings.graph_recursion_limit,
                },
                context=TravelRuntimeContext(user_id="anonymous"),
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
    if final_state.get("error") is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": final_state["error"],
                "message": "The agent planning runtime ended with a safe error.",
            },
        )
    if travel_plan is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=final_state.get("error") or "The Planner Agent did not return a plan.",
        )
    return travel_plan
