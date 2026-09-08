"""Safe, no-cost travel-data configuration status."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings
from app.core.config import Settings
from app.external.duffel.diagnostics import TravelDataStatus, build_travel_data_status

router = APIRouter(prefix="/api/v1/travel-data", tags=["travel-data"])


@router.get("/status", response_model=TravelDataStatus)
async def travel_data_status(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> TravelDataStatus:
    """Describe local provider configuration without contacting Duffel."""

    return build_travel_data_status(settings)
