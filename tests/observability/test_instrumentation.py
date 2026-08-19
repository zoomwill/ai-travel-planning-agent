"""P13 wrappers count real work once without changing behavior."""

import asyncio
import inspect
from typing import cast

import pytest
from prometheus_client import generate_latest

from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import TravelPlanningGraph
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.invoker import MCPToolInvoker
from app.mcp_tools.registry import MCPToolRegistry
from app.observability.instrumentation import (
    GraphRunTracker,
    InstrumentedAdvancedRetriever,
    InstrumentedSearchBackend,
    instrument_node,
    invoke_graph_once,
)
from app.observability.metrics import MetricsRuntime
from app.rag.models import AdvancedRetrievalResult, QueryBundle, RetrievalDiagnostics
from app.streaming.models import StreamBusinessEvent, StreamEventType
from app.streaming.service import TravelPlanStream
from tests.graphs.test_persistence import make_state
from tests.mcp_tools.helpers import async_tool, request, response
from tests.review.helpers import make_review_plan
from tests.search.helpers import RecordingSearchBackend
from tests.streaming.test_service import BlockingGraph, FakeGraph, final_chunk


def _metrics_text(metrics: MetricsRuntime) -> str:
    return generate_latest(metrics.registry).decode()


@pytest.mark.asyncio
async def test_node_wrapper_preserves_signature_result_and_exception_status() -> None:
    metrics = MetricsRuntime.create()

    def sync_node(value: int, *, add: int = 1) -> int:
        return value + add

    wrapped = instrument_node("planner", sync_node, metrics)
    assert inspect.signature(wrapped) == inspect.signature(sync_node)
    assert wrapped(2, add=3) == 5

    async def failing_node(value: int) -> int:
        raise RuntimeError(str(value))

    failing = instrument_node("reviewer", failing_node, metrics)
    with pytest.raises(RuntimeError):
        await failing(1)
    text = _metrics_text(metrics)
    assert 'node="planner",status="success"' in text
    assert 'node="reviewer",status="error"' in text


@pytest.mark.asyncio
async def test_graph_success_error_cancelled_are_each_counted_once() -> None:
    metrics = MetricsRuntime.create()
    success = await invoke_graph_once(
        lambda: asyncio.sleep(0, result={"error": None}),
        metrics=metrics,
        backend="direct",
    )
    assert success == {"error": None}
    error = await invoke_graph_once(
        lambda: asyncio.sleep(0, result={"error": "safe_code"}),
        metrics=metrics,
        backend="mcp",
    )
    assert error["error"] == "safe_code"
    tracker = GraphRunTracker(metrics, "direct", clock=iter((1.0, 2.0)).__next__)
    tracker.finish("cancelled")
    tracker.finish("success")
    text = _metrics_text(metrics)
    assert 'backend="direct",status="success"} 1.0' in text
    assert 'backend="mcp",status="error"} 1.0' in text
    assert 'backend="direct",status="cancelled"} 1.0' in text


@pytest.mark.asyncio
async def test_five_search_kinds_keep_parallel_backend_contract() -> None:
    metrics = MetricsRuntime.create()
    backend = InstrumentedSearchBackend(RecordingSearchBackend(), metrics, "direct")
    requirements = make_review_plan().requirements
    await asyncio.gather(
        backend.search_flights(requirements),
        backend.search_hotels(requirements),
        backend.search_attractions(requirements),
        backend.get_weather(requirements),
        backend.get_route(requirements.origin, requirements.destination),
    )
    text = _metrics_text(metrics)
    lines = [
        line for line in text.splitlines() if line.startswith("travel_planner_search_tasks_total{")
    ]
    for kind in ("flights", "hotels", "attractions", "weather", "route"):
        assert any(
            f'kind="{kind}"' in line and 'backend="direct"' in line and 'status="success"' in line
            for line in lines
        )


class _RagRetriever:
    async def retrieve(self, _: QueryBundle, **__: object) -> AdvancedRetrievalResult:
        return AdvancedRetrievalResult(
            contexts=["private context"],
            parent_ids=["parent-id"],
            diagnostics=RetrievalDiagnostics(
                pipeline_version="test",
                corpus_fingerprint="fingerprint",
                embedding_backend="test",
                embedding_model="test",
                query_variant_count=1,
                dense_candidate_count=1,
                sparse_candidate_count=1,
                fused_candidate_count=1,
                reranked_candidate_count=1,
                returned_parent_count=1,
                metadata_filter_applied=False,
                metadata_filter_fallback_used=False,
                cache_status="hit",
            ),
        )


@pytest.mark.asyncio
async def test_rag_and_mcp_metrics_do_not_expose_payloads() -> None:
    metrics = MetricsRuntime.create()
    retriever = InstrumentedAdvancedRetriever(_RagRetriever(), metrics)
    await retriever.retrieve(QueryBundle(original_query="private Tokyo query"))

    async def handler(request: dict[str, object]):
        del request
        payload = response("get_weather", data=[{"private": "supersecretresultvalue"}]).model_dump(
            mode="json"
        )
        return "ok", {"structured_content": payload}

    invoker = MCPToolInvoker(
        MCPToolRegistry([async_tool("get_weather", handler)]),
        timeout_seconds=1,
        max_retries=0,
        metrics=metrics,
    )
    await invoker.invoke("get_weather", request())
    text = _metrics_text(metrics)
    assert 'cache_status="hit",status="success"' in text
    mcp_line = next(
        line
        for line in text.splitlines()
        if line.startswith("travel_planner_mcp_tool_calls_total{")
    )
    assert 'status="success"' in mcp_line and 'tool="get_weather"' in mcp_line
    assert all(
        value not in text
        for value in ("private Tokyo query", "private context", "supersecretresultvalue")
    )


@pytest.mark.asyncio
async def test_mcp_failure_increments_error_once_without_fallback() -> None:
    metrics = MetricsRuntime.create()

    async def failing(request: dict[str, object]):
        del request
        raise OSError("private transport detail")

    invoker = MCPToolInvoker(
        MCPToolRegistry([async_tool("get_weather", failing)]),
        timeout_seconds=1,
        max_retries=0,
        metrics=metrics,
    )
    with pytest.raises(MCPToolLayerError) as captured:
        await invoker.invoke("get_weather", request())

    assert captured.value.error_type == "mcp_transport_unavailable"
    lines = [
        line
        for line in _metrics_text(metrics).splitlines()
        if line.startswith("travel_planner_mcp_tool_calls_total{")
    ]
    assert len(lines) == 1
    assert 'status="error"' in lines[0] and 'tool="get_weather"' in lines[0]
    assert lines[0].endswith(" 1.0")


def _stream(graph: FakeGraph, metrics: MetricsRuntime) -> TravelPlanStream:
    state = make_state()
    state["requirements"] = make_review_plan().requirements
    return TravelPlanStream(
        graph=cast(TravelPlanningGraph, graph),
        initial_state=state,
        config={"configurable": {"thread_id": "p13-stream"}},
        context=TravelRuntimeContext(user_id="p13-user", preferences_to_remember=()),
        thread_id="p13-stream",
        backend_mode="direct",
        heartbeat_seconds=60,
        queue_maxsize=2,
        metrics=metrics,
    )


@pytest.mark.asyncio
async def test_sse_success_and_disconnect_always_restore_active_gauge() -> None:
    success_metrics = MetricsRuntime.create()
    events = [item async for item in _stream(FakeGraph([final_chunk()]), success_metrics).stream()]
    assert isinstance(events[-1], StreamBusinessEvent)
    assert events[-1].event_type is StreamEventType.PLAN_COMPLETED
    success_text = _metrics_text(success_metrics)
    assert "travel_planner_sse_connections_active 0.0" in success_text
    assert 'terminal_status="success"} 1.0' in success_text
    assert 'event_type="plan_completed"} 1.0' in success_text

    disconnect_metrics = MetricsRuntime.create()
    graph = BlockingGraph()
    generator = _stream(graph, disconnect_metrics).stream()
    await anext(generator)
    await asyncio.wait_for(graph.started.wait(), timeout=1)
    await generator.aclose()
    await asyncio.wait_for(graph.closed.wait(), timeout=1)
    disconnect_text = _metrics_text(disconnect_metrics)
    assert "travel_planner_sse_connections_active 0.0" in disconnect_text
    assert "travel_planner_sse_disconnects_total 1.0" in disconnect_text
    assert 'terminal_status="disconnect"} 1.0' in disconnect_text
    assert 'event_type="ping"' not in disconnect_text


@pytest.mark.asyncio
async def test_sse_terminal_status_waits_until_downstream_accepts_terminal_event() -> None:
    metrics = MetricsRuntime.create()
    generator = _stream(FakeGraph([final_chunk()]), metrics).stream()
    terminal: StreamBusinessEvent | None = None
    while terminal is None or terminal.event_type is not StreamEventType.PLAN_COMPLETED:
        item = await anext(generator)
        if isinstance(item, StreamBusinessEvent):
            terminal = item

    await generator.aclose()

    text = _metrics_text(metrics)
    assert 'terminal_status="disconnect"} 1.0' in text
    assert 'terminal_status="success"}' not in text
    assert "travel_planner_sse_connections_active 0.0" in text
