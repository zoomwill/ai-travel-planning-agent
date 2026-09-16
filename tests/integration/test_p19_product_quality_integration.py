"""P19 quality survives real PostgreSQL reopen, including pre-P19 checkpoints."""

import asyncio
import os
from contextlib import asynccontextmanager
from functools import partial
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import PersistenceResources, create_strict_serializer
from app.domain.models import TravelPlan
from app.graphs.graph import build_travel_planning_graph
from app.main import create_app
from app.review.models import ReviewIssueCode
from tests.api.test_persistence import payload
from tests.helpers import make_resource_fakes
from tests.review.helpers import ScriptedPlanReviewer, ScriptedReviewStep, make_review_plan

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION_TESTS") != "1", reason="local PostgreSQL opt-in"),
]


@pytest.fixture
def postgres_quality_app():
    """Recreate connections per lifespan; clean only this test's unique thread."""
    settings = Settings()
    uri = settings.langgraph_postgres_uri.get_secret_value()
    thread_id = f"p19-quality-{uuid4().hex}"

    def factory(score):
        reviewer = ScriptedPlanReviewer(
            [
                ScriptedReviewStep(
                    score, score, score, score, (ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE,)
                )
            ]
        )

        async def resources(_):
            return make_resource_fakes(settings).resources

        @asynccontextmanager
        async def persistence(settings, *args, **kwargs):
            async with (
                AsyncPostgresSaver.from_conn_string(uri, serde=create_strict_serializer()) as saver,
                AsyncPostgresStore.from_conn_string(uri) as store,
            ):
                await saver.setup()
                await store.setup()
                graph = build_travel_planning_graph(
                    lambda query: [],
                    plan_reviewer=reviewer,
                    review_max_rounds=settings.review_max_rounds,
                    review_score_threshold=settings.review_score_threshold,
                    checkpointer=saver,
                    store=store,
                )
                yield PersistenceResources(saver, store, graph)

        return create_app(
            settings=settings, resource_factory=resources, persistence_factory=persistence
        )

    yield factory, thread_id, settings.review_max_rounds

    async def cleanup():
        async with AsyncPostgresSaver.from_conn_string(
            uri, serde=create_strict_serializer()
        ) as saver:
            await saver.adelete_thread(thread_id)

    asyncio.run(cleanup())


def prevent_graph_execution(graph, monkeypatch):
    """Read-only restoration must fail the test if it attempts any execution."""
    for name in ("ainvoke", "astream", "invoke", "stream"):
        monkeypatch.setattr(graph, name, AsyncMock(side_effect=AssertionError("read reran graph")))


@pytest.mark.parametrize("score,status", [(95, "accepted"), (60, "forced_finalized")])
def test_quality_and_route_warning_survive_postgres_reopen(
    postgres_quality_app, monkeypatch, score, status
):
    factory, thread_id, max_rounds = postgres_quality_app
    root = f"/api/v1/agents/threads/{thread_id}"
    config = {"configurable": {"thread_id": thread_id}}
    assert os.getenv("LANGGRAPH_STRICT_MSGPACK") == "true"
    assert create_strict_serializer().pickle_fallback is False

    with TestClient(factory(score)) as client:
        response = client.post(root + "/plans", json=payload())
        assert response.status_code == 200
        plan = response.json()["travel_plan"]
        assert plan["quality"]["review_status"] == status
        assert plan["quality"]["final_score"] == score
        assert response.json()["review_rounds"] == (1 if status == "accepted" else max_rounds)
        snapshot = client.portal.call(client.app.state.persistence.graph.aget_state, config)
        assert len(snapshot.values["search_tasks"]) == 5
        assert len(snapshot.values["search_results"]) == 4
        assert snapshot.values["search_summary"]["route"]["status"] == "error"
        assert "route_unavailable" in plan["warnings"]

    # New application, graph, checkpointer, store, and PostgreSQL connections.
    with TestClient(factory(score)) as reopened:
        graph = reopened.app.state.persistence.graph
        prevent_graph_execution(graph, monkeypatch)
        snapshot = reopened.portal.call(graph.aget_state, config)
        assert isinstance(snapshot.values["travel_plan"], TravelPlan)
        assert snapshot.values["travel_plan"].model_dump(mode="json") == plan
        state = reopened.get(root + "/state")
        history = reopened.get(root + "/history")
        assert state.status_code == history.status_code == 200
        assert state.json()["status"] == "complete"
        assert state.json()["travel_plan"] == plan
        assert history.json()["checkpoints"][0]["quality"] == plan["quality"]
        assert history.json()["checkpoints"][0]["warnings"] == plan["warnings"]


def test_pre_p19_checkpoint_is_unknown_and_never_rewritten(postgres_quality_app, monkeypatch):
    factory, thread_id, _ = postgres_quality_app
    root = f"/api/v1/agents/threads/{thread_id}"
    config = {"configurable": {"thread_id": thread_id}}
    old_plan = make_review_plan().model_dump(mode="json")
    old_plan.pop("quality")
    old_plan.pop("warnings")
    old_plan["daily_itinerary"][0]["activities"].append("Legacy public_transit 29 minutes")
    with TestClient(factory(95)) as client:
        graph = client.app.state.persistence.graph
        client.portal.call(
            partial(graph.aupdate_state, config, {"travel_plan": old_plan}, as_node="finalize_plan")
        )
        saved = client.portal.call(graph.aget_state, config)

    with TestClient(factory(95)) as reopened:
        graph = reopened.app.state.persistence.graph
        prevent_graph_execution(graph, monkeypatch)
        state = reopened.get(root + "/state")
        history = reopened.get(root + "/history")
        assert state.status_code == history.status_code == 200
        plan = state.json()["travel_plan"]
        assert plan["quality"]["review_status"] == "unavailable"
        assert plan["quality"]["final_score"] is None
        assert "historical_route_unverified" in plan["warnings"]
        assert "Legacy public_transit 29 minutes" in plan["daily_itinerary"][0]["activities"]
        assert history.json()["checkpoints"][0]["quality"] == plan["quality"]
        after_read = reopened.portal.call(graph.aget_state, config)
        assert after_read.config == saved.config
        assert after_read.values == saved.values
        assert "quality" not in after_read.values["travel_plan"]
