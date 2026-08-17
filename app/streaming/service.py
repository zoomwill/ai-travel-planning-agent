"""Single-execution LangGraph producer, heartbeat, and cancellation service."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing, suppress
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from app.domain.models import TravelPlan
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import TravelPlanningGraph
from app.graphs.state import TravelPlanState
from app.search.models import JsonObject
from app.streaming.mapper import LangGraphEventMapper
from app.streaming.models import (
    StreamBusinessEvent,
    StreamEventDraft,
    StreamEventStatus,
    StreamEventType,
    StreamHeartbeat,
)

_PRODUCER_DONE = object()
_TERMINAL_EVENTS = {StreamEventType.PLAN_COMPLETED, StreamEventType.ERROR}


class EventSequencer:
    """Assign one connection's monotonic identity and UTC timestamp."""

    def __init__(
        self,
        thread_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sequence = 0

    def next(self, draft: StreamEventDraft) -> StreamBusinessEvent:
        """Create the next event; heartbeats deliberately never call this method."""

        self._sequence += 1
        return StreamBusinessEvent(
            **draft.model_dump(),
            event_id=self._sequence,
            thread_id=self._thread_id,
            sequence=self._sequence,
            timestamp=self._clock(),
        )


class TravelPlanStream:
    """Project one persistent graph execution into safe ordered stream items."""

    def __init__(
        self,
        *,
        graph: TravelPlanningGraph,
        initial_state: TravelPlanState,
        config: RunnableConfig,
        context: TravelRuntimeContext,
        thread_id: str,
        backend_mode: str,
        heartbeat_seconds: float,
        queue_maxsize: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._graph = graph
        self._initial_state = initial_state
        self._config = config
        self._context = context
        self._thread_id = thread_id
        self._backend_mode = backend_mode
        self._heartbeat_seconds = heartbeat_seconds
        self._queue_maxsize = queue_maxsize
        self._sequencer = EventSequencer(thread_id, clock=clock)

    async def stream(self) -> AsyncGenerator[StreamBusinessEvent | StreamHeartbeat, None]:
        """Yield progress and cleanly cancel/await the graph producer on disconnect."""

        queue: asyncio.Queue[StreamBusinessEvent | object] = asyncio.Queue(
            maxsize=self._queue_maxsize
        )
        run_started = self._sequencer.next(
            StreamEventDraft(
                event_type=StreamEventType.RUN_STARTED,
                node="agent_runtime",
                status=StreamEventStatus.STARTED,
                message="Persistent travel planning started.",
                data={"backend_mode": self._backend_mode, "persistent": True},
            )
        )
        yield run_started

        producer = asyncio.create_task(
            self._produce(queue),
            name=f"travel-plan-stream-{self._thread_id}",
        )
        try:
            while True:
                try:
                    async with asyncio.timeout(self._heartbeat_seconds):
                        item = await queue.get()
                except TimeoutError:
                    yield StreamHeartbeat()
                    continue
                if item is _PRODUCER_DONE:
                    break
                event = cast(StreamBusinessEvent, item)
                yield event
                if event.event_type in _TERMINAL_EVENTS:
                    break
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

    async def _produce(self, queue: asyncio.Queue[StreamBusinessEvent | object]) -> None:
        mapper = LangGraphEventMapper()
        terminal_sent = False
        try:
            raw_stream = cast(
                AsyncGenerator[dict[str, Any], None],
                self._graph.astream(
                    self._initial_state,
                    config=self._config,
                    context=self._context,
                    stream_mode=["tasks", "updates"],
                    version="v2",
                ),
            )
            async with aclosing(raw_stream) as chunks:
                async for chunk in chunks:
                    for draft in mapper.map_chunk(chunk):
                        await queue.put(self._sequencer.next(draft))

            if mapper.final_plan is None and mapper.state_error is None:
                snapshot = await self._graph.aget_state(self._config)
                mapper.observe_final_state(snapshot.values)
            if (
                mapper.state_error is not None
                or mapper.final_plan is None
                or not self._plan_matches_request(mapper.final_plan)
            ):
                await queue.put(self._error_event(mapper.state_error))
            else:
                await queue.put(self._plan_event(mapper))
            terminal_sent = True
        except asyncio.CancelledError:
            raise
        except GraphRecursionError:
            if not terminal_sent:
                await queue.put(
                    self._error_event("graph_recursion_limit_reached", recoverable=False)
                )
        except Exception:
            if not terminal_sent:
                await queue.put(self._error_event("stream_graph_failed"))
        finally:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(_PRODUCER_DONE)

    def _plan_matches_request(self, plan: TravelPlan) -> bool:
        """Reject a checkpoint plan that belongs to an older thread request."""

        requirements = self._initial_state.get("requirements")
        return requirements is not None and plan.requirements == requirements

    def _plan_event(self, mapper: LangGraphEventMapper) -> StreamBusinessEvent:
        plan = cast(TravelPlan, mapper.final_plan)
        data: JsonObject = {"travel_plan": cast(JsonObject, plan.model_dump(mode="json"))}
        review = mapper.current_review
        if mapper.review_status is not None:
            data["review_status"] = mapper.review_status
        if review is not None:
            data["review_rounds"] = review.review_round
            data["final_score"] = review.scores.overall_score
        if mapper.finalization_reason is not None:
            data["finalization_reason"] = mapper.finalization_reason
        return self._sequencer.next(
            StreamEventDraft(
                event_type=StreamEventType.PLAN_COMPLETED,
                node="finalize_plan",
                status=StreamEventStatus.COMPLETED,
                message="The validated travel plan is complete.",
                data=data,
            )
        )

    def _error_event(
        self,
        state_error: str | None,
        *,
        recoverable: bool = True,
    ) -> StreamBusinessEvent:
        error_code, safe_message = _safe_stream_error(state_error)
        return self._sequencer.next(
            StreamEventDraft(
                event_type=StreamEventType.ERROR,
                node="agent_runtime",
                status=StreamEventStatus.FAILED,
                message=safe_message,
                data={
                    "error_code": error_code,
                    "safe_message": safe_message,
                    "recoverable": recoverable,
                },
            )
        )


def _safe_stream_error(error: str | None) -> tuple[str, str]:
    """Map State or runtime failure to stable text without exception details."""

    if error is not None and error.startswith("critical_search_failed:"):
        return "critical_search_failed", "Required flight or hotel search data is unavailable."
    messages = {
        "store_unavailable": "The preference store is unavailable.",
        "checkpoint_unavailable": "The persistent checkpoint is unavailable.",
        "plan_assembly_failed": "The validated search results could not be assembled.",
        "reviewer_failed": "The quality review could not complete.",
        "review_output_invalid": "The quality review returned invalid data.",
        "revision_failed": "The requested plan revision could not complete.",
        "finalization_failed": "The final travel plan could not be validated.",
        "graph_recursion_limit_reached": "The graph reached its configured safety limit.",
        "stream_graph_failed": "The planning stream could not complete.",
    }
    if error in messages:
        return error, messages[error]
    return "stream_invalid_final_state", "The planning stream ended without a valid final plan."
