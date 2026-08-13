"""Opt-in PostgreSQL integration tests for durable P09 reflection state."""

import json
import os
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.memory.preferences import list_user_preferences
from app.review.models import ReviewIssueCode
from tests.graphs.test_persistence import config, make_state
from tests.integration.test_persistence_integration import assert_current_destination
from tests.review.helpers import ScriptedPlanReviewer, ScriptedReviewStep

pytestmark = pytest.mark.integration

PASS_STEP = ScriptedReviewStep(100, 100, 100, 100)
REVISION_STEP = ScriptedReviewStep(
    100,
    100,
    0,
    100,
    (ReviewIssueCode.PERSONALIZATION_MISSING,),
)
FORCED_STEP = ScriptedReviewStep(
    100,
    100,
    100,
    0,
    (ReviewIssueCode.BUDGET_OVERRUN,),
)


def state_for_route(origin: str, destination: str):
    """Create one complete request while retaining the standard integration dates."""

    state = make_state()
    state["requirements"] = state["requirements"].model_copy(
        update={"origin": origin, "destination": destination}
    )
    state["user_request"] = f"{origin} to {destination} travel plan"
    return state


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check PostgreSQL P09 review state",
)
@pytest.mark.asyncio
async def test_postgres_revision_reset_and_memory_survive_reopen() -> None:
    """Multi-round review, same-thread reset, and user memory persist safely."""

    assert os.getenv("LANGGRAPH_STRICT_MSGPACK") == "true"
    serializer = create_strict_serializer()
    assert serializer.pickle_fallback is False
    settings = Settings()
    uri = settings.langgraph_postgres_uri.get_secret_value()
    unique = uuid4().hex
    revision_thread = f"p09-{unique}-revision"
    reset_thread = f"p09-{unique}-reset"
    memory_thread = f"p09-{unique}-memory"
    isolated_thread = f"p09-{unique}-isolated"
    thread_ids = (revision_thread, reset_thread, memory_thread, isolated_thread)
    user_id = f"p09-{unique}-user"
    other_user_id = f"p09-{unique}-other"
    preference_id = ""

    try:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as saver:
            async with AsyncPostgresStore.from_conn_string(uri) as store:
                await saver.setup()
                await store.setup()
                revision_reviewer = ScriptedPlanReviewer([REVISION_STEP, PASS_STEP])
                revision_graph = build_travel_planning_graph(
                    lambda query: [],
                    plan_reviewer=revision_reviewer,
                    checkpointer=saver,
                    store=store,
                )
                revised = await revision_graph.ainvoke(
                    state_for_route("Shanghai", "Paris"),
                    config=config(revision_thread),
                    context=TravelRuntimeContext(
                        user_id=user_id,
                        preferences_to_remember=("Quiet neighborhoods",),
                    ),
                )
                assert revision_reviewer.calls == 2
                assert revised["review_round"] == 2
                assert revised["review_status"] == "accepted"
                assert revised["finalization_reason"] == "threshold_reached"
                assert len(revised["review_history"]) == 2
                assert len({entry["draft_fingerprint"] for entry in revised["review_history"]}) == 2
                assert isinstance(revised["travel_plan"], TravelPlan)

                reset_reviewer = ScriptedPlanReviewer([PASS_STEP])
                reset_graph = build_travel_planning_graph(
                    lambda query: [],
                    plan_reviewer=reset_reviewer,
                    checkpointer=saver,
                    store=store,
                )
                tokyo = await reset_graph.ainvoke(
                    state_for_route("Shanghai", "Tokyo"),
                    config=config(reset_thread),
                    context=TravelRuntimeContext(user_id=user_id),
                )
                paris = await reset_graph.ainvoke(
                    state_for_route("Tokyo", "Paris"),
                    config=config(reset_thread),
                    context=TravelRuntimeContext(user_id=user_id),
                )
                assert (
                    tokyo["review_history"][0]["draft_fingerprint"]
                    != paris["review_history"][0]["draft_fingerprint"]
                )
                assert paris["review_round"] == 1
                assert len(paris["review_history"]) == 1
                assert len(paris["search_results"]) == 5
                assert_current_destination(paris["search_results"], "Paris")

                remembered = await reset_graph.ainvoke(
                    state_for_route("Osaka", "Paris"),
                    config=config(memory_thread),
                    context=TravelRuntimeContext(user_id=user_id),
                )
                isolated = await reset_graph.ainvoke(
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
                revision_snapshot = await reopened_graph.aget_state(config(revision_thread))
                reset_snapshot = await reopened_graph.aget_state(config(reset_thread))
                revision_history = [
                    item
                    async for item in reopened_graph.aget_state_history(config(revision_thread))
                ]
                task_names = {task.name for snapshot in revision_history for task in snapshot.tasks}
                preferences = await list_user_preferences(reopened_store, user_id)
                other_preferences = await list_user_preferences(reopened_store, other_user_id)

                assert revision_snapshot.values["review_status"] == "accepted"
                assert revision_snapshot.values["review_round"] == 2
                assert len(revision_snapshot.values["review_history"]) == 2
                restored_rounds = [
                    entry["review_round"] for entry in revision_snapshot.values["review_history"]
                ]
                assert restored_rounds == [
                    1,
                    2,
                ]
                assert isinstance(revision_snapshot.values["draft_plan"], dict)
                assert isinstance(revision_snapshot.values["travel_plan"], TravelPlan)
                assert {"planner", "reviewer", "finalize_plan"} <= task_names
                json.dumps(revision_snapshot.values["review_history"])

                assert reset_snapshot.values["requirements"].destination == "Paris"
                assert reset_snapshot.values["review_round"] == 1
                assert len(reset_snapshot.values["review_history"]) == 1
                assert_current_destination(reset_snapshot.values["search_results"], "Paris")
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


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check PostgreSQL P09 max rounds",
)
@pytest.mark.asyncio
async def test_postgres_forced_finalize_survives_reopen() -> None:
    """A continuously low score persists exactly max rounds and an honest final plan."""

    settings = Settings()
    uri = settings.langgraph_postgres_uri.get_secret_value()
    thread_id = f"p09-{uuid4().hex}-forced"
    reviewer = ScriptedPlanReviewer([FORCED_STEP])

    try:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as saver:
            async with AsyncPostgresStore.from_conn_string(uri) as store:
                graph = build_travel_planning_graph(
                    lambda query: [],
                    plan_reviewer=reviewer,
                    review_max_rounds=2,
                    checkpointer=saver,
                    store=store,
                )
                result = await graph.ainvoke(
                    make_state(),
                    config=config(thread_id),
                    context=TravelRuntimeContext(user_id=f"{thread_id}-user"),
                )
                assert reviewer.calls == 2
                assert result["review_round"] == 2
                assert result["review_status"] == "forced_finalized"
                assert result["finalization_reason"] == "max_review_rounds_reached"
                assert len(result["review_history"]) == 2

        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as reopened_saver:
            reopened_graph = build_travel_planning_graph(checkpointer=reopened_saver)
            snapshot = await reopened_graph.aget_state(config(thread_id))

            assert snapshot.values["review_round"] == 2
            assert snapshot.values["review_status"] == "forced_finalized"
            assert snapshot.values["finalization_reason"] == "max_review_rounds_reached"
            assert "maximum review rounds were reached" in snapshot.values["travel_plan"].markdown
    finally:
        async with AsyncPostgresSaver.from_conn_string(
            uri,
            serde=create_strict_serializer(),
        ) as cleanup_saver:
            await cleanup_saver.adelete_thread(thread_id)
