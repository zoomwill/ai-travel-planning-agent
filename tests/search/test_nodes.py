"""Unit tests for P08 prepare, Send, worker, and aggregator nodes."""

import json

import pytest
from langgraph.types import Overwrite, Send

from app.graphs.nodes.aggregate_search_results import aggregate_search_results_node
from app.graphs.nodes.prepare_search_tasks import (
    dispatch_search_tasks,
    prepare_search_tasks_node,
)
from app.graphs.nodes.search_worker import search_worker_node
from app.graphs.state import TravelPlanState
from app.search.models import (
    SEARCH_KIND_ORDER,
    SearchErrorEnvelope,
    SearchKind,
    SearchKindValue,
    SearchResultEnvelope,
    SearchWorkerInput,
    create_search_tasks,
    dump_model_json,
)
from tests.search.helpers import RecordingSearchBackend
from tests.search.test_models import make_requirements


def test_prepare_uses_overwrite_to_reset_every_accumulated_field() -> None:
    """A new request bypasses reducers instead of merging old task data."""

    requirements = make_requirements()
    state: TravelPlanState = {
        "requirements": requirements,
        "next_agent": "planner",
        "search_tasks": create_search_tasks(make_requirements("Paris")),
        "search_results": [],
        "tool_errors": [],
        "search_summary": {"weather": {"status": "error", "count": 0}},
        "error": None,
    }

    update = prepare_search_tasks_node(state)

    assert isinstance(update["search_tasks"], Overwrite)
    assert len(update["search_tasks"].value) == 5
    assert update["search_results"] == Overwrite(value=[])
    assert update["tool_errors"] == Overwrite(value=[])
    assert update["search_summary"] == Overwrite(value={})


def test_dispatch_builds_five_minimal_json_safe_send_payloads() -> None:
    """Dispatcher fans out without including backend, clients, or app resources."""

    requirements = make_requirements()
    sends = dispatch_search_tasks(
        {
            "requirements": requirements,
            "search_tasks": create_search_tasks(requirements),
            "error": None,
        }
    )

    assert isinstance(sends, list)
    assert len(sends) == 5
    assert all(isinstance(send, Send) and send.node == "search_worker" for send in sends)
    payloads = [send.arg for send in sends]
    assert [payload["search_task"]["kind"] for payload in payloads] == [
        kind.value for kind in SEARCH_KIND_ORDER
    ]
    assert all(set(payload) == {"search_task", "requirements_data"} for payload in payloads)
    json.dumps(payloads)


@pytest.mark.parametrize("kind", list(SearchKind))
async def test_worker_calls_only_the_dispatched_backend_method(kind: SearchKind) -> None:
    """One generic worker behaves as exactly one specialized subagent."""

    requirements = make_requirements()
    task = next(task for task in create_search_tasks(requirements) if task["kind"] == kind.value)
    backend = RecordingSearchBackend()
    worker_input = SearchWorkerInput(
        search_task=task,
        requirements_data=dump_model_json(requirements),
    )

    update = await search_worker_node(worker_input, backend=backend)

    if kind is SearchKind.ROUTE:
        assert "search_results" not in update
        assert update["tool_errors"][0]["error_type"] == "route_unavailable"
        assert update["tool_errors"][0]["recoverable"] is False
    else:
        assert len(update["search_results"]) == 1
        assert update["search_results"][0]["kind"] == kind.value
    assert backend.calls[kind] == 1
    assert sum(backend.calls.values()) == 1
    json.dumps(update)


async def test_worker_converts_private_provider_failure_to_safe_error() -> None:
    """A branch failure cannot leak exception text or kill sibling branches."""

    requirements = make_requirements()
    task = create_search_tasks(requirements)[0]
    update = await search_worker_node(
        SearchWorkerInput(
            search_task=task,
            requirements_data=dump_model_json(requirements),
        ),
        backend=RecordingSearchBackend(fail_kind=SearchKind.FLIGHTS),
    )

    assert update["tool_errors"][0]["kind"] == "flights"
    assert update["tool_errors"][0]["error_type"] == "provider_error"
    assert "private backend detail" not in json.dumps(update)


def successful_result(kind: SearchKindValue, count: int) -> SearchResultEnvelope:
    """Build a result with a configurable aggregate count."""

    return SearchResultEnvelope(
        task_id=f"{kind}-task",
        kind=kind,
        status="ok",
        data=[{"index": index} for index in range(count)],
    )


def test_aggregator_summary_ignores_result_arrival_order() -> None:
    """Fan-in emits fixed kind order and counts independent of worker completion."""

    results = [
        successful_result("route", 1),
        successful_result("weather", 5),
        successful_result("flights", 2),
        successful_result("attractions", 3),
        successful_result("hotels", 2),
    ]

    first = aggregate_search_results_node({"search_results": results, "tool_errors": []})
    second = aggregate_search_results_node(
        {"search_results": list(reversed(results)), "tool_errors": []}
    )

    assert first == second
    assert first["search_summary"] == {
        "flights": {"status": "ok", "count": 2, "source": "demo"},
        "hotels": {"status": "ok", "count": 2, "source": "demo"},
        "attractions": {"status": "ok", "count": 3, "source": "demo"},
        "weather": {"status": "ok", "count": 5, "source": "demo"},
        "route": {"status": "ok", "count": 1, "source": "demo"},
    }


def test_aggregator_marks_failed_kind_without_removing_successes() -> None:
    """One error remains visible while every sibling result is retained."""

    weather_error = SearchErrorEnvelope(
        task_id="weather-task",
        kind="weather",
        error_type="provider_error",
        safe_message="Weather search unavailable.",
        recoverable=True,
    )
    result = aggregate_search_results_node(
        {
            "search_results": [
                successful_result("flights", 2),
                successful_result("hotels", 2),
                successful_result("attractions", 3),
                successful_result("route", 1),
            ],
            "tool_errors": [weather_error],
        }
    )

    assert result["search_summary"]["weather"] == {
        "status": "error",
        "count": 0,
        "source": "demo",
    }
    assert result["search_summary"]["flights"] == {
        "status": "ok",
        "count": 2,
        "source": "demo",
    }
