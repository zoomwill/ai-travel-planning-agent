"""Small test doubles for application-owned resources."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.persistence import (
    PersistenceFactory,
    PersistenceResources,
    create_strict_serializer,
)
from app.core.resources import AppResources
from app.graphs.graph import build_travel_planning_graph
from app.graphs.nodes.retriever import ContextRetriever
from app.infrastructure.chroma import ChromaClientProvider
from app.rag.advanced_retriever import AdvancedRetriever
from app.review.reviewer import PlanReviewer
from app.search.backend import SearchBackend


class FakeEngine:
    """Record disposal without opening a database connection."""

    def __init__(self, close_error: Exception | None = None) -> None:
        self.dispose_calls = 0
        self.close_error = close_error

    async def dispose(self) -> None:
        """Record one disposal attempt."""

        self.dispose_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeRedis:
    """Record closure without opening a Redis connection."""

    def __init__(self, close_error: Exception | None = None) -> None:
        self.close_calls = 0
        self.close_error = close_error

    async def aclose(self) -> None:
        """Record one close attempt."""

        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeChroma:
    """Provide controllable heartbeat and close behavior."""

    def __init__(
        self,
        *,
        heartbeat_error: Exception | None = None,
        heartbeat_delay: float = 0,
        close_error: Exception | None = None,
    ) -> None:
        self.heartbeat_error = heartbeat_error
        self.heartbeat_delay = heartbeat_delay
        self.close_error = close_error
        self.heartbeat_calls = 0
        self.close_calls = 0

    async def heartbeat(self) -> None:
        """Return, fail, or pause according to the test setup."""

        self.heartbeat_calls += 1
        if self.heartbeat_delay:
            await asyncio.sleep(self.heartbeat_delay)
        if self.heartbeat_error is not None:
            raise self.heartbeat_error

    async def aclose(self) -> None:
        """Record one close attempt."""

        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


@dataclass(slots=True)
class ResourceFakes:
    """Keep typed application resources and inspectable doubles together."""

    resources: AppResources
    engine: FakeEngine
    redis: FakeRedis
    chroma: FakeChroma


def make_resource_fakes(
    settings: Settings,
    *,
    engine: FakeEngine | None = None,
    redis: FakeRedis | None = None,
    chroma: FakeChroma | None = None,
) -> ResourceFakes:
    """Build resources that never contact Docker services."""

    fake_engine = engine or FakeEngine()
    fake_redis = redis or FakeRedis()
    fake_chroma = chroma or FakeChroma()
    resources = AppResources(
        settings=settings,
        postgres_engine=cast(AsyncEngine, fake_engine),
        redis_client=cast(Redis, fake_redis),
        chroma_client=cast(ChromaClientProvider, fake_chroma),
    )
    return ResourceFakes(
        resources=resources,
        engine=fake_engine,
        redis=fake_redis,
        chroma=fake_chroma,
    )


def make_in_memory_persistence_factory(
    context_retriever: ContextRetriever | None = None,
    search_backend: SearchBackend | None = None,
    plan_reviewer: PlanReviewer | None = None,
) -> PersistenceFactory:
    """Build isolated LangGraph persistence that never contacts Docker."""

    retrieve = context_retriever or (lambda query: [])

    @asynccontextmanager
    async def factory(
        settings: Settings,
        advanced_retriever: AdvancedRetriever | None = None,
    ) -> AsyncIterator[PersistenceResources]:
        checkpointer = InMemorySaver(serde=create_strict_serializer())
        store = InMemoryStore()
        graph = build_travel_planning_graph(
            retrieve,
            advanced_retriever=advanced_retriever,
            search_backend=search_backend,
            plan_reviewer=plan_reviewer,
            review_score_threshold=settings.review_score_threshold,
            review_max_rounds=settings.review_max_rounds,
            checkpointer=checkpointer,
            store=store,
        )
        yield PersistenceResources(
            checkpointer=checkpointer,
            store=store,
            graph=graph,
        )

    return factory
