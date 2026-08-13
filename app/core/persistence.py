"""Application-owned LangGraph checkpoint and preference-store resources."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import BaseStore
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.graphs.graph import TravelPlanningGraph, build_travel_planning_graph


@dataclass(frozen=True, slots=True)
class PersistenceResources:
    """One running application's checkpointer, store, and compiled graph."""

    checkpointer: BaseCheckpointSaver[str]
    store: BaseStore
    graph: TravelPlanningGraph


PersistenceFactory = Callable[[Settings], AbstractAsyncContextManager[PersistenceResources]]


def create_strict_serializer() -> JsonPlusSerializer:
    """Create a MessagePack serializer that never falls back to pickle."""

    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=None,
    )


@asynccontextmanager
async def create_postgres_persistence_resources(
    settings: Settings,
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
