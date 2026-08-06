"""Health-check route."""

from fastapi import APIRouter

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = get_settings()) -> dict[str, str]:
    """Return a minimal liveness response."""

    return {"status": "ok", "service": settings.app_name}
