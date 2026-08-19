"""Application-owned LangGraph checkpoint and preference-store resources."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import BaseStore
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.graphs.graph import TravelPlanningGraph, build_travel_planning_graph
from app.observability.metrics import MetricsRuntime
from app.rag.advanced_retriever import AdvancedRetriever
from app.search.backend import SearchBackend


@dataclass(frozen=True, slots=True)
class PersistenceResources:
    """One running application's checkpointer, store, and compiled graph."""

    checkpointer: BaseCheckpointSaver[str]
    store: BaseStore
    graph: TravelPlanningGraph


class PersistenceFactory(Protocol):
    """Create persistence while allowing the P11 backend argument to stay optional."""

    def __call__(
        self,
        settings: Settings,
        advanced_retriever: AdvancedRetriever | None = None,
        search_backend: SearchBackend | None = None,
        metrics: MetricsRuntime | None = None,
        backend_mode: str = "direct",
    ) -> AbstractAsyncContextManager[PersistenceResources]:
        """Return an application-owned persistence context manager."""


def create_strict_serializer() -> JsonPlusSerializer:
    """Create a MessagePack serializer that never falls back to pickle."""

    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=None,
    )


@asynccontextmanager
async def create_postgres_persistence_resources(
    settings: Settings,
    advanced_retriever: AdvancedRetriever | None = None,
    search_backend: SearchBackend | None = None,
    metrics: MetricsRuntime | None = None,
    backend_mode: str = "direct",
) -> AsyncIterator[PersistenceResources]:
    """Open exactly one saver and store connection for one application lifespan."""

    connection_uri = settings.langgraph_postgres_uri.get_secret_value()
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(
                connection_uri,
                serde=create_strict_serializer(),
            )
        )
        store = await stack.enter_async_context(AsyncPostgresStore.from_conn_string(connection_uri))
        graph = build_travel_planning_graph(
            advanced_retriever=advanced_retriever,
            search_backend=search_backend,
            review_score_threshold=settings.review_score_threshold,
            review_max_rounds=settings.review_max_rounds,
            checkpointer=checkpointer,
            store=store,
            metrics=metrics,
            backend_mode=backend_mode,
        )
        yield PersistenceResources(
            checkpointer=checkpointer,
            store=store,
            graph=graph,
        )
