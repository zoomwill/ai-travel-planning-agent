"""Tests for resource creation and cleanup across application lifespans."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.core import resources as resources_module
from app.core.config import Settings
from app.core.persistence import PersistenceResources
from app.core.resources import AppResources, close_app_resources, create_app_resources
from app.main import create_app
from tests.helpers import (
    FakeEngine,
    FakeRedis,
    make_in_memory_persistence_factory,
    make_resource_fakes,
)


def test_lifespan_creates_and_closes_resources() -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)
    factory_calls = 0

    async def resource_factory(_: Settings) -> AppResources:
        nonlocal factory_calls
        factory_calls += 1
        return fakes.resources

    app = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    assert not hasattr(app.state, "resources")

    with TestClient(app):
        assert app.state.resources is fakes.resources

    assert factory_calls == 1
    assert not hasattr(app.state, "resources")
    assert fakes.chroma.close_calls == 1
    assert fakes.redis.close_calls == 1
    assert fakes.engine.dispose_calls == 1


@pytest.mark.asyncio
async def test_partial_initialization_disposes_created_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    engine = FakeEngine()

    def fail_redis(_: Settings) -> FakeRedis:
        raise RuntimeError("redis constructor failed")

    monkeypatch.setattr(resources_module, "create_postgres_engine", lambda _: engine)
    monkeypatch.setattr(resources_module, "create_redis_client", fail_redis)

    with pytest.raises(RuntimeError, match="redis constructor failed"):
        await create_app_resources(settings)

    assert engine.dispose_calls == 1


def test_same_app_can_run_two_complete_lifespans() -> None:
    settings = Settings(_env_file=None)
    created = []

    async def resource_factory(_: Settings) -> AppResources:
        fakes = make_resource_fakes(settings)
        created.append(fakes)
        return fakes.resources

    app = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    for _ in range(2):
        with TestClient(app):
            assert hasattr(app.state, "resources")
        assert not hasattr(app.state, "resources")

    assert len(created) == 2
    assert all(fakes.chroma.close_calls == 1 for fakes in created)
    assert all(fakes.redis.close_calls == 1 for fakes in created)
    assert all(fakes.engine.dispose_calls == 1 for fakes in created)


@pytest.mark.asyncio
async def test_cleanup_attempts_every_resource_before_raising() -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(
        settings,
        engine=FakeEngine(close_error=RuntimeError("engine close failed")),
        redis=FakeRedis(close_error=RuntimeError("redis close failed")),
    )

    with pytest.raises(ExceptionGroup) as captured:
        await close_app_resources(fakes.resources)

    assert len(captured.value.exceptions) == 2
    assert fakes.chroma.close_calls == 1
    assert fakes.redis.close_calls == 1
    assert fakes.engine.dispose_calls == 1


def test_persistence_startup_failure_still_closes_infrastructure() -> None:
    """A partial P07 startup must not leak resources created by P02."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    @asynccontextmanager
    async def failing_persistence_factory(
        _: Settings,
    ) -> AsyncIterator[PersistenceResources]:
        raise RuntimeError("persistence startup failed")
        yield

    app = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=failing_persistence_factory,
    )

    with pytest.raises(RuntimeError, match="persistence startup failed"):
        with TestClient(app):
            pass

    assert fakes.chroma.close_calls == 1
    assert fakes.redis.close_calls == 1
    assert fakes.engine.dispose_calls == 1
