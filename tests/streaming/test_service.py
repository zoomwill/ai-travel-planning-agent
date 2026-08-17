"""Single execution, terminal, heartbeat, and cancellation tests."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import TravelPlanningGraph
from app.graphs.state import TravelPlanState
from app.streaming.models import StreamBusinessEvent, StreamEventType, StreamHeartbeat
from app.streaming.service import TravelPlanStream
from tests.graphs.test_persistence import make_state
from tests.review.helpers import make_review_plan


class FakeGraph:
    """Record public graph calls and yield controlled v2 chunks."""

    def __init__(
        self,
        chunks: list[dict[str, Any]],
        *,
        final_values: dict[str, Any] | None = None,
        error: Exception | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.chunks = chunks
        self.final_values = final_values or {}
        self.error = error
        self.delay_seconds = delay_seconds
        self.astream_calls = 0
        self.aget_state_calls = 0
        self.ainvoke_calls = 0
        self.stream_mode: object = None
        self.version: object = None

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        """Yield chunks once and optionally fail without exposing the detail."""

        del args
        self.astream_calls += 1
        self.stream_mode = kwargs.get("stream_mode")
        self.version = kwargs.get("version")
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def aget_state(self, config: object) -> object:
        """Return a checkpoint-shaped object without executing the graph."""

        del config
        self.aget_state_calls += 1
        return SimpleNamespace(values=self.final_values)

    async def ainvoke(self, *args: object, **kwargs: object) -> object:
        """Fail loudly if production ever tries the forbidden fallback."""

        del args, kwargs
        self.ainvoke_calls += 1
        raise AssertionError("ainvoke must never be used by streaming")


def final_chunk() -> dict[str, Any]:
    """Return the installed v2 update shape containing a validated final plan."""

    return {
        "type": "updates",
        "data": {
            "finalize_plan": {
                "travel_plan": make_review_plan().model_dump(mode="json"),
                "error": None,
            }
        },
    }


def make_stream(
    graph: FakeGraph,
    *,
    heartbeat: float = 1,
    initial_state: TravelPlanState | None = None,
    queue_maxsize: int = 2,
) -> TravelPlanStream:
    """Create one stream with a deterministic clock and fake graph."""

    if initial_state is None:
        initial_state = make_state()
        initial_state["requirements"] = make_review_plan().requirements
    return TravelPlanStream(
        graph=cast(TravelPlanningGraph, graph),
        initial_state=initial_state,
        config={"configurable": {"thread_id": "stream-thread"}, "recursion_limit": 50},
        context=TravelRuntimeContext(user_id="user-a"),
        thread_id="stream-thread",
        backend_mode="direct",
        heartbeat_seconds=heartbeat,
        queue_maxsize=queue_maxsize,
        clock=lambda: datetime(2026, 8, 17, 8, 30, tzinfo=UTC),
    )


async def collect(stream: TravelPlanStream) -> list[StreamBusinessEvent | StreamHeartbeat]:
    """Consume one test stream to its terminal event."""

    return [item async for item in stream.stream()]


@pytest.mark.asyncio
async def test_graph_executes_once_and_plan_terminal_is_exactly_once() -> None:
    graph = FakeGraph([final_chunk()])
    items = await collect(make_stream(graph))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]

    assert events[0].event_type is StreamEventType.RUN_STARTED
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.event_id for event in events] == [event.sequence for event in events]
    assert events[-1].event_type is StreamEventType.PLAN_COMPLETED
    assert sum(event.event_type is StreamEventType.PLAN_COMPLETED for event in events) == 1
    assert graph.astream_calls == 1
    assert graph.stream_mode == ["tasks", "updates"]
    assert graph.version == "v2"
    assert graph.aget_state_calls == 0
    assert graph.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_missing_update_uses_checkpoint_read_without_second_execution() -> None:
    plan = make_review_plan()
    graph = FakeGraph([], final_values={"travel_plan": plan, "error": None})
    items = await collect(make_stream(graph))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]

    assert events[-1].event_type is StreamEventType.PLAN_COMPLETED
    assert events[-1].data["travel_plan"]["requirements"]["destination"] == "Tokyo"
    assert graph.astream_calls == 1
    assert graph.aget_state_calls == 1
    assert graph.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_failure_update_never_reads_or_returns_an_older_checkpoint_plan() -> None:
    old_plan = make_review_plan()
    graph = FakeGraph(
        [
            {
                "type": "updates",
                "data": {
                    "aggregate_search_results": {
                        "error": "critical_search_failed:flights",
                    }
                },
            }
        ],
        final_values={"travel_plan": old_plan, "error": None},
    )
    items = await collect(make_stream(graph))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]

    assert events[-1].event_type is StreamEventType.ERROR
    assert events[-1].data["error_code"] == "critical_search_failed"
    assert all(event.event_type is not StreamEventType.PLAN_COMPLETED for event in events)
    assert graph.astream_calls == 1
    assert graph.aget_state_calls == 0
    assert graph.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_checkpoint_fallback_rejects_plan_for_an_older_request() -> None:
    state = make_state()
    state["requirements"] = state["requirements"].model_copy(update={"destination": "Paris"})
    graph = FakeGraph([], final_values={"travel_plan": make_review_plan(), "error": None})
    items = await collect(make_stream(graph, initial_state=state))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]

    assert events[-1].event_type is StreamEventType.ERROR
    assert events[-1].data["error_code"] == "stream_invalid_final_state"
    assert all(event.event_type is not StreamEventType.PLAN_COMPLETED for event in events)
    assert graph.astream_calls == 1
    assert graph.aget_state_calls == 1
    assert graph.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_graph_exception_sends_one_sanitized_error_and_no_plan() -> None:
    private = "postgresql://user:password@host/db traceback Bearer secret File /Users/private"
    graph = FakeGraph([], error=RuntimeError(private))
    items = await collect(make_stream(graph))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]
    serialized = repr(events)

    assert events[-1].event_type is StreamEventType.ERROR
    assert sum(event.event_type is StreamEventType.ERROR for event in events) == 1
    assert all(event.event_type is not StreamEventType.PLAN_COMPLETED for event in events)
    assert events[-1].data["error_code"] == "stream_graph_failed"
    assert all(secret not in serialized for secret in (private, "postgresql://", "Bearer"))
    assert graph.astream_calls == 1
    assert graph.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_full_bounded_queue_still_delivers_one_terminal_error() -> None:
    chunks = [
        {
            "type": "tasks",
            "data": {"id": f"node-{index}", "name": "router", "input": {}},
        }
        for index in range(10)
    ]
    graph = FakeGraph(chunks, error=RuntimeError("private producer failure"))
    items = await asyncio.wait_for(
        collect(make_stream(graph, queue_maxsize=1)),
        timeout=1,
    )
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]

    assert events[-1].event_type is StreamEventType.ERROR
    assert sum(event.event_type is StreamEventType.ERROR for event in events) == 1
    assert all(event.event_type is not StreamEventType.PLAN_COMPLETED for event in events)
    assert graph.astream_calls == 1


@pytest.mark.asyncio
async def test_idle_heartbeat_does_not_consume_business_sequence() -> None:
    graph = FakeGraph([final_chunk()], delay_seconds=0.03)
    items = await collect(make_stream(graph, heartbeat=0.005))
    events = [item for item in items if isinstance(item, StreamBusinessEvent)]
    heartbeats = [item for item in items if isinstance(item, StreamHeartbeat)]

    assert heartbeats
    assert all(heartbeat.comment == "ping" for heartbeat in heartbeats)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type is StreamEventType.PLAN_COMPLETED
    assert isinstance(items[-1], StreamBusinessEvent)


class BlockingGraph(FakeGraph):
    """Hold the graph open so test cancellation can inspect cleanup."""

    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.release = asyncio.Event()

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        del args, kwargs
        self.astream_calls += 1
        self.started.set()
        try:
            await self.release.wait()
            if False:
                yield {}
        finally:
            self.closed.set()


class QueueFillingGraph(FakeGraph):
    """Fill a tiny queue until disconnect cancellation closes this stream."""

    def __init__(self) -> None:
        super().__init__([])
        self.closed = asyncio.Event()

    async def astream(self, *args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        del args, kwargs
        self.astream_calls += 1
        try:
            for index in range(100):
                yield {
                    "type": "tasks",
                    "data": {"id": f"node-{index}", "name": "router", "input": {}},
                }
        finally:
            self.closed.set()


@pytest.mark.asyncio
async def test_disconnect_cancels_and_awaits_producer_without_terminal_event() -> None:
    graph = BlockingGraph()
    generator = make_stream(graph, heartbeat=60).stream()
    first = await anext(generator)
    assert isinstance(first, StreamBusinessEvent)
    assert first.event_type is StreamEventType.RUN_STARTED

    pending = asyncio.create_task(anext(generator))
    await asyncio.wait_for(graph.started.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await generator.aclose()

    await asyncio.wait_for(graph.closed.wait(), timeout=1)
    assert graph.astream_calls == 1
    assert graph.ainvoke_calls == 0
    assert not any(
        task.get_name() == "travel-plan-stream-stream-thread" and not task.done()
        for task in asyncio.all_tasks()
    )


@pytest.mark.asyncio
async def test_disconnect_with_full_queue_does_not_deadlock_cleanup() -> None:
    graph = QueueFillingGraph()
    generator = make_stream(graph, heartbeat=60, queue_maxsize=1).stream()
    first = await anext(generator)
    second = await anext(generator)
    assert isinstance(first, StreamBusinessEvent)
    assert isinstance(second, StreamBusinessEvent)
    await asyncio.sleep(0)

    await asyncio.wait_for(generator.aclose(), timeout=1)

    await asyncio.wait_for(graph.closed.wait(), timeout=1)
    assert graph.astream_calls == 1
    assert not any(
        task.get_name() == "travel-plan-stream-stream-thread" and not task.done()
        for task in asyncio.all_tasks()
    )
