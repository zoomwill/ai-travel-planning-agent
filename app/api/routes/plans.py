"""HTTP boundary for the deterministic Phase P04 planning service."""

from fastapi import APIRouter, HTTPException, status

from app.domain.models import TravelPlan, TripRequirements
from app.services import planning_service

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


@router.post(
    "/mock",
    response_model=TravelPlan,
    status_code=status.HTTP_200_OK,
    summary="Create a deterministic mock travel plan",
)
def create_mock_plan(requirements: TripRequirements) -> TravelPlan:
    """Validate one request and return a plan without real external calls."""

    try:
        return planning_service.create_mock_travel_plan(requirements)
    except planning_service.PlanningServiceError as exc:
        detail = f"Mock travel planning could not be completed during {exc.stage}."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc
