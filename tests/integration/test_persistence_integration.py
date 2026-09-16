"""Opt-in PostgreSQL round-trip test for P07 memory and P08 search state."""

import json
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
from app.search.models import SEARCH_KIND_ORDER, create_request_fingerprint
from tests.graphs.test_persistence import config, make_state

pytestmark = pytest.mark.integration


def state_for_route(origin: str, destination: str):
    """Build one complete graph input for an integration-test route."""

    state = make_state()
    state["requirements"] = state["requirements"].model_copy(
        update={"origin": origin, "destination": destination}
    )
    state["user_request"] = f"{origin} to {destination} travel plan"
    return state


def assert_current_destination(search_results: list[dict[str, object]], destination: str) -> None:
    """Confirm every result uses the current request rather than the old destination."""

    for envelope in search_results:
        kind = envelope["kind"]
        data = envelope["data"]
        assert isinstance(data, list) and data
        if kind == "flights":
            assert all(item["destination"] == destination for item in data)
        elif kind in {"hotels", "attractions", "weather"}:
            assert all(item["city"] == destination for item in data)
        else:
            assert data[0]["destination"] == destination


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check local PostgreSQL persistence",
)
@pytest.mark.asyncio
async def test_postgres_parallel_state_and_user_memory_survive_reopen() -> None:
    """Official Postgres resources persist reset P08 state and isolated P07 memory."""

    assert os.getenv("LANGGRAPH_STRICT_MSGPACK") == "true"
    settings = Settings()
    uri = settings.langgraph_postgres_uri.get_secret_value()
    unique = uuid4().hex
    main_thread = f"p08-{unique}-main"
    memory_thread = f"p08-{unique}-memory"
    isolated_thread = f"p08-{unique}-isolated"
    thread_ids = (main_thread, memory_thread, isolated_thread)
    user_id = f"p08-{unique}-user"
    other_user_id = f"p08-{unique}-other"
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
                first = await graph.ainvoke(
                    state_for_route("Shanghai", "Tokyo"),
                    config=config(main_thread),
                    context=TravelRuntimeContext(
                        user_id=user_id,
                        preferences_to_remember=("Quiet neighborhoods",),
                    ),
                )
                assert isinstance(first["travel_plan"], TravelPlan)
                assert len(first["search_results"]) == 4
                assert len({item["task_id"] for item in first["search_results"]}) == 4
                assert first["search_summary"]["route"]["status"] == "error"
                assert len(first["search_tasks"]) == 5

                second_state = state_for_route("Tokyo", "Paris")
                second = await graph.ainvoke(
                    second_state,
                    config=config(main_thread),
                    context=TravelRuntimeContext(user_id=user_id),
                )
                expected_fingerprint = create_request_fingerprint(second_state["requirements"])
                assert len(second["search_results"]) == 4
                assert {task["request_fingerprint"] for task in second["search_tasks"]} == {
                    expected_fingerprint
                }
                assert_current_destination(second["search_results"], "Paris")

                remembered = await graph.ainvoke(
                    state_for_route("Osaka", "Paris"),
                    config=config(memory_thread),
                    context=TravelRuntimeContext(user_id=user_id),
                )
                isolated = await graph.ainvoke(
                    state_for_route("Osaka", "Paris"),
                    config=config(isolated_thread),
                    context=TravelRuntimeContext(user_id=other_user_id),
                )
                assert remembered["remembered_preferences"] == ["Quiet neighborhoods"]
                assert isolated["remembered_preferences"] == []
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
                snapshot = await reopened_graph.aget_state(config(main_thread))
                history = [
                    item async for item in reopened_graph.aget_state_history(config(main_thread))
                ]
                preferences = await list_user_preferences(reopened_store, user_id)
                other_preferences = await list_user_preferences(reopened_store, other_user_id)

                assert isinstance(snapshot.values["requirements"], TripRequirements)
                assert isinstance(snapshot.values["travel_plan"], TravelPlan)
                assert snapshot.values["requirements"].destination == "Paris"
                assert len(snapshot.values["search_tasks"]) == 5
                assert len(snapshot.values["search_results"]) == 4
                assert len({item["task_id"] for item in snapshot.values["search_results"]}) == 4
                assert [item["kind"] for item in snapshot.values["search_results"]] == [
                    kind.value for kind in SEARCH_KIND_ORDER if kind.value != "route"
                ]
                assert_current_destination(snapshot.values["search_results"], "Paris")
                json.dumps(snapshot.values["search_results"])
                assert history
                assert [item.value for item in preferences] == ["Quiet neighborhoods"]
                assert other_preferences == []
    finally:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as cleanup_saver:
            for thread_id in thread_ids:
                await cleanup_saver.adelete_thread(thread_id)
        async with AsyncPostgresStore.from_conn_string(uri) as cleanup_store:
            if preference_id:
                await cleanup_store.adelete(
                    (user_id, "travel_preferences"),
                    preference_id,
                )
