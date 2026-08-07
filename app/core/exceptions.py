"""Structured exceptions shared by infrastructure adapters."""

from enum import StrEnum


class InfrastructureService(StrEnum):
    """Names of infrastructure services the application can probe."""

    POSTGRESQL = "postgresql"
    REDIS = "redis"
    CHROMA = "chroma"


class InfrastructureError(RuntimeError):
    """Report which service failed without exposing connection details."""

    def __init__(self, service: InfrastructureService) -> None:
        self.service = service
        super().__init__(f"{service.value} readiness check failed")
