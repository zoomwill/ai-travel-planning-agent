"""P19 factual limitations, bounded review projection, and strict persistence."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.domain.quality import PlanQuality, PlanWarning
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.graphs.nodes.planner import planner_node
from app.review.models import ReviewIssueCode
from app.review.presentation import present_plan
from app.services.mock_providers.route_provider import RouteUnavailableError, get_route
from tests.graphs.test_persistence import config, make_state
from tests.graphs.test_planner import make_completed_search_state
from tests.review.helpers import ScriptedPlanReviewer, ScriptedReviewStep, make_review_plan
from tests.search.helpers import BarrierSearchBackend


@pytest.mark.parametrize(
    "places", [("Cleveland", "Tokyo"), ("Shanghai", "Paris"), ("Tokyo Station", "Asakusa")]
)
def test_no_unverified_route_duration_or_quote(places):
    with pytest.raises(RouteUnavailableError):
        get_route(*places)


def test_legacy_route_never_enters_planner_draft():
    state = make_completed_search_state()
    plan = TravelPlan.model_validate(planner_node(state)["draft_plan"])
    assert "public_transit" not in plan.markdown
    assert "29 minutes" not in plan.markdown
    assert "Route information unavailable." in plan.markdown
    assert PlanWarning.ROUTE_UNAVAILABLE in plan.warnings


@pytest.mark.parametrize("score,status,rounds", [(95, "accepted", 1), (60, "forced_finalized", 3)])
async def test_terminal_quality_survives_readonly_strict_checkpoint(
    score, status, rounds, monkeypatch
):
    backend = BarrierSearchBackend()
    backend.release.set()
    reviewer = ScriptedPlanReviewer(
        [
            ScriptedReviewStep(
                score, score, score, score, (ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE,)
            )
        ]
    )
    graph = build_travel_planning_graph(
        lambda _: [],
        search_backend=backend,
        plan_reviewer=reviewer,
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    result = await graph.ainvoke(
        make_state(), config=config("p19-quality"), context=TravelRuntimeContext(user_id="p19-only")
    )
    plan = result["travel_plan"]
    assert plan.quality.review_status == status
    assert plan.quality.final_score == score
    assert plan.quality.review_rounds == rounds
    assert reviewer.calls == rounds
    assert len(backend.started) == 5 and all(v == 1 for v in backend.calls.values())
    assert result["search_summary"]["route"]["status"] == "error"
    assert result["error"] is None
    assert PlanWarning.ROUTE_UNAVAILABLE in plan.warnings

    async def forbidden(*args, **kwargs):
        raise AssertionError("Restore executed graph")

    monkeypatch.setattr(graph, "ainvoke", forbidden)
    snapshot = await graph.aget_state(config("p19-quality"))
    restored = present_plan(snapshot.values["travel_plan"], snapshot.values)
    assert restored == plan
    assert any(
        item.values.get("travel_plan")
        for item in [s async for s in graph.aget_state_history(config("p19-quality"))]
    )


def test_historical_plan_unknown_and_warning_without_rewriting_saved_data():
    raw = make_review_plan().model_dump(mode="json")
    raw.pop("quality")
    raw.pop("warnings")
    raw["daily_itinerary"][0]["activities"].append("Legacy public_transit 29 minutes")
    original = deepcopy(raw)
    restored = present_plan(TravelPlan.model_validate(raw), {})
    assert restored.quality == PlanQuality()
    assert PlanWarning.HISTORICAL_ROUTE_UNVERIFIED in restored.warnings
    assert raw == original
    assert "Legacy public_transit 29 minutes" in restored.daily_itinerary[0].activities


@pytest.mark.parametrize(
    "update",
    [
        {"final_score": float("nan")},
        {"final_score": 101},
        {"issue_codes": ["private arbitrary text"]},
        {"prompt": "not public"},
    ],
)
def test_quality_contract_rejects_unbounded_or_internal_fields(update):
    with pytest.raises(ValidationError):
        PlanQuality.model_validate(update)


def test_failed_review_cannot_project_as_accepted():
    result = present_plan(
        make_review_plan(), {"review_status": "accepted", "error": "reviewer_failed"}
    )
    assert result.quality.review_status == "unavailable"
