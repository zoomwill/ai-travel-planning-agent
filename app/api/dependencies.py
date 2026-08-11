"""FastAPI dependencies that read application-owned state."""

from typing import Annotated, cast

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.persistence import PersistenceResources
from app.core.resources import AppResources
from app.infrastructure.chroma import ChromaClientProvider


def get_app_settings(request: Request) -> Settings:
    """Return settings attached by the application factory."""

    return cast(Settings, request.app.state.settings)


def get_app_resources(request: Request) -> AppResources:
    """Return resources created by the active lifespan."""

    try:
        resources = request.app.state.resources
    except AttributeError as exc:
        raise RuntimeError("application resources are not initialized") from exc
    return cast(AppResources, resources)


def get_persistence_resources(request: Request) -> PersistenceResources:
    """Return LangGraph resources created by the active application lifespan."""

    try:
        persistence = request.app.state.persistence
    except AttributeError as exc:
        raise RuntimeError("persistence resources are not initialized") from exc
    return cast(PersistenceResources, persistence)


def get_postgres_engine(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> AsyncEngine:
    """Return the application's PostgreSQL engine."""

    return resources.postgres_engine


def get_redis_client(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> Redis:
    """Return the application's Redis client."""

    return resources.redis_client


def get_chroma_client(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> ChromaClientProvider:
    """Return the application's lazy Chroma provider."""

    return resources.chroma_client
