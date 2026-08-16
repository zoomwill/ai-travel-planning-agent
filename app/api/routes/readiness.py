"""Readiness endpoint for application infrastructure dependencies."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_app_resources
from app.core.resources import AppResources
from app.infrastructure.postgres import check_postgres
from app.infrastructure.redis import check_redis
from app.schemas.readiness import (
    InfrastructureReadiness,
    ReadinessResponse,
    ServiceReadiness,
    ServiceStatus,
)

router = APIRouter(tags=["health"])


async def run_probe(
    probe: Callable[[], Awaitable[None]],
    timeout_seconds: float,
) -> ServiceStatus:
    """Run one readiness probe with a deadline and a safe public result."""

    try:
        await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except Exception:
        return "error"
    return "ok"


async def run_boolean_probe(
    probe: Callable[[], Awaitable[bool]],
    timeout_seconds: float,
) -> ServiceStatus:
    """Require a bounded readiness predicate to explicitly return true."""

    try:
        ready = await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except Exception:
        return "error"
    return "ok" if ready else "error"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
    responses={503: {"model": ReadinessResponse}},
)
@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
    responses={503: {"model": ReadinessResponse}},
    include_in_schema=False,
)
async def readiness(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> ReadinessResponse | JSONResponse:
    """Report ready only when PostgreSQL, Redis, and Chroma all respond."""

    timeout = resources.settings.infrastructure_timeout_seconds
    postgresql_status, redis_status, chroma_status = await asyncio.gather(
        run_probe(lambda: check_postgres(resources.postgres_engine), timeout),
        run_probe(lambda: check_redis(resources.redis_client), timeout),
        run_probe(resources.chroma_client.heartbeat, timeout),
    )

    mcp_status: ServiceStatus | None = None
    if resources.settings.travel_search_backend_mode == "mcp":
        if resources.mcp_runtime is None:
            mcp_status = "error"
        else:
            mcp_status = await run_boolean_probe(
                resources.mcp_runtime.is_ready,
                resources.settings.mcp_discovery_timeout_seconds,
            )

    services = InfrastructureReadiness(
        postgresql=ServiceReadiness(status=postgresql_status),
        redis=ServiceReadiness(status=redis_status),
        chroma=ServiceReadiness(status=chroma_status),
        mcp=ServiceReadiness(status=mcp_status) if mcp_status is not None else None,
    )
    statuses = [postgresql_status, redis_status, chroma_status]
    if mcp_status is not None:
        statuses.append(mcp_status)
    is_ready = all(status == "ok" for status in statuses)
    response = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        services=services,
    )

    if not is_ready:
        return JSONResponse(
            status_code=503,
            content=response.model_dump(mode="json", exclude_none=True),
        )
    return response
