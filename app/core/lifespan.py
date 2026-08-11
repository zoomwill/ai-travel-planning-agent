"""FastAPI lifespan wiring for application-owned resources."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.persistence import (
    PersistenceFactory,
    create_postgres_persistence_resources,
)
from app.core.resources import (
    ResourceFactory,
    close_app_resources,
    create_app_resources,
)

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_lifespan(
    settings: Settings,
    resource_factory: ResourceFactory = create_app_resources,
    persistence_factory: PersistenceFactory = create_postgres_persistence_resources,
) -> Lifespan:
    """Build a lifespan that owns infrastructure and persistence resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = await resource_factory(settings)
        app.state.resources = resources
        try:
            async with persistence_factory(settings) as persistence:
                app.state.persistence = persistence
                try:
                    yield
                finally:
                    del app.state.persistence
        finally:
            try:
                await close_app_resources(resources)
            finally:
                del app.state.resources

    return lifespan
