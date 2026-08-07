"""Health-check route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings
from app.core.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/health/live", include_in_schema=False)
async def health(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, str]:
    """Return liveness without contacting any external service."""

    return {"status": "ok", "service": settings.app_name}
