"""Opt-in PostgreSQL round-trip test for P07 saver and store durability."""

import os
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan, TripRequirements
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.memory.preferences import list_user_preferences
from tests.graphs.test_persistence import config, make_state

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check local PostgreSQL persistence",
)
@pytest.mark.asyncio
async def test_postgres_checkpoint_and_store_survive_reopen() -> None:
    """Official Postgres resources persist typed state and isolated user memory."""

    assert os.getenv("LANGGRAPH_STRICT_MSGPACK") == "true"
    settings = Settings()
    uri = settings.langgraph_postgres_uri.get_secret_value()
    unique = uuid4().hex
    thread_id = f"p07-{unique}-thread"
    user_id = f"p07-{unique}-user"
    other_user_id = f"p07-{unique}-other"
    preference_id = ""

    try:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as saver:
            async with AsyncPostgresStore.from_conn_string(uri) as store:
                await saver.setup()
                await store.setup()
                graph = build_travel_planning_graph(
                    lambda query: [],
                    checkpointer=saver,
                    store=store,
                )
                result = await graph.ainvoke(
                    make_state(),
                    config=config(thread_id),
                    context=TravelRuntimeContext(
                        user_id=user_id,
                        preferences_to_remember=("Quiet neighborhoods",),
                    ),
                )
                assert isinstance(result["travel_plan"], TravelPlan)
                preference_id = (await list_user_preferences(store, user_id))[0].preference_id

        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as reopened_saver:
            async with AsyncPostgresStore.from_conn_string(uri) as reopened_store:
                reopened_graph = build_travel_planning_graph(
                    lambda query: [],
                    checkpointer=reopened_saver,
                    store=reopened_store,
                )
                snapshot = await reopened_graph.aget_state(config(thread_id))
                history = [
                    item async for item in reopened_graph.aget_state_history(config(thread_id))
                ]
                preferences = await list_user_preferences(reopened_store, user_id)
                isolated = await list_user_preferences(reopened_store, other_user_id)

                assert isinstance(snapshot.values["requirements"], TripRequirements)
                assert isinstance(snapshot.values["travel_plan"], TravelPlan)
                assert len(history) >= 6
                assert [item.value for item in preferences] == ["Quiet neighborhoods"]
                assert isolated == []
    finally:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as cleanup_saver:
            await cleanup_saver.adelete_thread(thread_id)
        async with AsyncPostgresStore.from_conn_string(uri) as cleanup_store:
            if preference_id:
                await cleanup_store.adelete(
                    (user_id, "travel_preferences"),
                    preference_id,
                )
