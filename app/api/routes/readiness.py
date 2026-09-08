"""Readiness endpoint for application infrastructure dependencies."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
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
    request: Request,
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

    qwen_status: ServiceStatus | None = None
    if resources.settings.agent_reasoning_mode == "qwen":
        runtime = resources.llm_runtime
        qwen_status = (
            "ok"
            if runtime is not None
            and runtime.provider is not None
            and runtime.diagnostics.configured
            and runtime.diagnostics.initialization_error is None
            else "error"
        )

    duffel_status: ServiceStatus | None = None
    if resources.settings.needs_duffel:
        duffel_status = "ok" if resources.settings.duffel_is_configured else "error"
    liteapi_status: ServiceStatus | None = None
    if resources.settings.requires_guest_nationality:
        liteapi_status = "ok" if resources.settings.liteapi_is_configured else "error"

    services = InfrastructureReadiness(
        postgresql=ServiceReadiness(status=postgresql_status),
        redis=ServiceReadiness(status=redis_status),
        chroma=ServiceReadiness(status=chroma_status),
        mcp=ServiceReadiness(status=mcp_status) if mcp_status is not None else None,
        qwen=ServiceReadiness(status=qwen_status) if qwen_status is not None else None,
        duffel=(ServiceReadiness(status=duffel_status) if duffel_status is not None else None),
        liteapi=(ServiceReadiness(status=liteapi_status) if liteapi_status is not None else None),
    )
    statuses = [postgresql_status, redis_status, chroma_status]
    if mcp_status is not None:
        statuses.append(mcp_status)
    if qwen_status is not None:
        statuses.append(qwen_status)
    if duffel_status is not None:
        statuses.append(duffel_status)
    if liteapi_status is not None:
        statuses.append(liteapi_status)
    metrics = request.app.state.metrics
    metrics.dependency_ready.labels(dependency="postgresql").set(
        1 if postgresql_status == "ok" else 0
    )
    metrics.dependency_ready.labels(dependency="redis").set(1 if redis_status == "ok" else 0)
    metrics.dependency_ready.labels(dependency="chroma").set(1 if chroma_status == "ok" else 0)
    if mcp_status is not None:
        mcp_ready = 1 if mcp_status == "ok" else 0
        http_ready = mcp_ready
        stdio_ready = mcp_ready
        if resources.mcp_runtime is not None:
            servers = resources.mcp_runtime.diagnostics.servers
            if "travel_tools" in servers:
                http_ready = 1 if servers["travel_tools"].ready else 0
            if "local_tools" in servers:
                stdio_ready = 1 if servers["local_tools"].ready else 0
        metrics.dependency_ready.labels(dependency="mcp_http").set(http_ready)
        metrics.dependency_ready.labels(dependency="mcp_stdio").set(stdio_ready)
    if qwen_status is not None:
        metrics.dependency_ready.labels(dependency="qwen").set(1 if qwen_status == "ok" else 0)
    if duffel_status is not None:
        metrics.dependency_ready.labels(dependency="duffel").set(1 if duffel_status == "ok" else 0)
    if liteapi_status is not None:
        metrics.dependency_ready.labels(dependency="liteapi").set(
            1 if liteapi_status == "ok" else 0
        )
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
