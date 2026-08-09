"""HTTP boundary for the deterministic Phase P05 LangGraph runtime."""

from typing import cast

from fastapi import APIRouter, HTTPException, status

from app.domain.models import TravelPlan, TripRequirements
from app.graphs.graph import travel_planning_graph
from app.graphs.state import TravelPlanState

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.post(
    "/plans",
    response_model=TravelPlan,
    status_code=status.HTTP_200_OK,
    summary="Create a deterministic plan through LangGraph",
)
def create_agent_plan(requirements: TripRequirements) -> TravelPlan:
    """Run validated requirements through Router and Planner graph nodes."""

    initial_state: TravelPlanState = {
        "user_request": (f"Plan a trip from {requirements.origin} to {requirements.destination}"),
        "requirements": requirements,
        "next_agent": None,
        "travel_plan": None,
        "error": None,
    }

    try:
        final_state = cast(TravelPlanState, travel_planning_graph.invoke(initial_state))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The agent planning runtime could not complete the request.",
        ) from exc

    travel_plan = final_state.get("travel_plan")
    if travel_plan is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=final_state.get("error") or "The Planner Agent did not return a plan.",
        )
    return travel_plan
