"""FastAPI lifespan wiring for application-owned resources."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.resources import (
    ResourceFactory,
    close_app_resources,
    create_app_resources,
)

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_lifespan(
    settings: Settings,
    resource_factory: ResourceFactory = create_app_resources,
) -> Lifespan:
    """Build a lifespan that owns exactly one resource container per run."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = await resource_factory(settings)
        app.state.resources = resources
        try:
            yield
        finally:
            try:
                await close_app_resources(resources)
            finally:
                del app.state.resources

    return lifespan
