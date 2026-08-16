"""Structured readiness response models."""

from typing import Literal

from pydantic import BaseModel

ServiceStatus = Literal["ok", "error"]
OverallStatus = Literal["ready", "not_ready"]


class ServiceReadiness(BaseModel):
    """Public status for one infrastructure service."""

    status: ServiceStatus


class InfrastructureReadiness(BaseModel):
    """Public statuses for every P02 infrastructure dependency."""

    postgresql: ServiceReadiness
    redis: ServiceReadiness
    chroma: ServiceReadiness
    mcp: ServiceReadiness | None = None


class ReadinessResponse(BaseModel):
    """Response returned by the readiness endpoints."""

    status: OverallStatus
    services: InfrastructureReadiness
