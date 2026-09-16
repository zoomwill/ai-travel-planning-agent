"""One terminal, identical durable summary, no graph execution on reads."""

import json
from functools import partial
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.review.models import ReviewIssueCode
from tests.api.test_persistence import client as client
from tests.api.test_persistence import payload
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.review.helpers import ScriptedPlanReviewer, ScriptedReviewStep, make_review_plan


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("score,status", [(95, "accepted"), (60, "forced_finalized")])
def test_quality_equal_in_response_state_and_history(stream, score, status, monkeypatch):
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resources(_):
        return fakes.resources

    reviewer = ScriptedPlanReviewer(
        [
            ScriptedReviewStep(
                score, score, score, score, (ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE,)
            )
        ]
    )
    app = create_app(
        settings=settings,
        resource_factory=resources,
        persistence_factory=make_in_memory_persistence_factory(plan_reviewer=reviewer),
    )
    root = "/api/v1/agents/threads/p19-quality"
    with TestClient(app) as client:
        response = client.post(root + ("/plans/stream" if stream else "/plans"), json=payload())
        assert response.status_code == 200
        if stream:
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert sum(e["event_type"] == "plan_completed" for e in events) == 1
            assert not any(e["event_type"] == "error" for e in events)
            assert events[-1]["event_type"] == "plan_completed"
            assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
            plan = events[-1]["data"]["travel_plan"]
        else:
            plan = response.json()["travel_plan"]
        assert plan["quality"]["review_status"] == status
        assert plan["quality"]["final_score"] == score
        assert "route_unavailable" in plan["warnings"]
        graph = app.state.persistence.graph
        monkeypatch.setattr(
            graph, "ainvoke", AsyncMock(side_effect=AssertionError("read reran graph"))
        )
        state = client.get(root + "/state").json()
        history = client.get(root + "/history").json()["checkpoints"]
        assert state["travel_plan"]["quality"] == plan["quality"]
        assert state["travel_plan"]["warnings"] == plan["warnings"]
        assert history[0]["quality"] == plan["quality"]
        assert history[0]["warnings"] == plan["warnings"]


def test_old_checkpoint_restores_unknown_quality_without_execution_or_rewrite(client, monkeypatch):
    graph = client.app.state.persistence.graph
    config = {"configurable": {"thread_id": "p19-old-record"}}
    old_plan = make_review_plan().model_dump(mode="json")
    old_plan.pop("quality")
    old_plan.pop("warnings")
    old_plan["daily_itinerary"][0]["activities"].append("Legacy public_transit 29 minutes")
    client.portal.call(
        partial(graph.aupdate_state, config, {"travel_plan": old_plan}, as_node="finalize_plan")
    )
    saved = client.portal.call(graph.aget_state, config)
    monkeypatch.setattr(graph, "ainvoke", AsyncMock(side_effect=AssertionError("read reran graph")))
    monkeypatch.setattr(graph, "astream", AsyncMock(side_effect=AssertionError("read reran graph")))
    root = "/api/v1/agents/threads/p19-old-record"
    state = client.get(root + "/state")
    assert state.status_code == 200
    plan = state.json()["travel_plan"]
    assert plan["quality"]["review_status"] == "unavailable"
    assert plan["quality"]["final_score"] is None
    assert "historical_route_unverified" in plan["warnings"]
    assert "Legacy public_transit 29 minutes" in plan["daily_itinerary"][0]["activities"]
    history = client.get(root + "/history").json()["checkpoints"]
    assert history[0]["quality"] == plan["quality"]
    assert client.portal.call(graph.aget_state, config).values == saved.values
