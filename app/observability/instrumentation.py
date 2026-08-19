"""Small wrappers around real graph, RAG, search, and node executions."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from app.observability.metrics import (
    BACKENDS,
    CACHE_STATUSES,
    FINALIZATION_REASONS,
    GRAPH_NODES,
    REVIEW_STATUSES,
    SEARCH_KINDS,
    STATUSES,
    MetricsRuntime,
    normalize_label,
)
from app.rag.advanced_retriever import AdvancedRetriever
from app.rag.models import AdvancedRetrievalResult, QueryBundle, RetrievalMode
from app.search.backend import SearchBackend
from app.search.models import SearchKindValue

P = ParamSpec("P")
R = TypeVar("R")
Clock = Callable[[], float]


class GraphRunTracker:
    """Record exactly one outcome for one already-running graph execution."""

    def __init__(
        self,
        metrics: MetricsRuntime,
        backend: str,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self._metrics = metrics
        self._backend = normalize_label(backend, BACKENDS)
        self._clock = clock
        self._started = clock()
        self._finished = False

    def finish(self, status: str) -> None:
        """Record once even if cleanup paths race with a terminal event."""

        if self._finished:
            return
        self._finished = True
        normalized = normalize_label(status, STATUSES)
        duration = max(0.0, self._clock() - self._started)
        self._metrics.graph_runs.labels(backend=self._backend, status=normalized).inc()
        self._metrics.graph_duration.labels(backend=self._backend, status=normalized).observe(
            duration
        )


async def invoke_graph_once(
    operation: Callable[[], Awaitable[R]],
    *,
    metrics: MetricsRuntime,
    backend: str,
) -> R:
    """Observe a caller-provided graph invocation without invoking it again."""

    tracker = GraphRunTracker(metrics, backend)
    try:
        result = await operation()
    except asyncio.CancelledError:
        tracker.finish("cancelled")
        raise
    except BaseException:
        tracker.finish("error")
        raise
    state = result if isinstance(result, dict) else {}
    tracker.finish("error" if state.get("error") else "success")
    return result


def instrument_node(
    node_name: str,
    node: Callable[P, R] | Callable[P, Awaitable[R]],
    metrics: MetricsRuntime,
    *,
    clock: Clock = time.monotonic,
) -> Callable[P, R] | Callable[P, Awaitable[R]]:
    """Preserve a node signature while recording success, error, or cancellation."""

    normalized_node = normalize_label(node_name, GRAPH_NODES)
    if inspect.iscoroutinefunction(node):

        @wraps(node)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = clock()
            status = "success"
            try:
                result = await cast(Callable[P, Awaitable[R]], node)(*args, **kwargs)
                if isinstance(result, dict) and result.get("error"):
                    status = "error"
                return result
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except BaseException:
                status = "error"
                raise
            finally:
                metrics.graph_node_duration.labels(
                    node=normalized_node,
                    status=normalize_label(status, STATUSES),
                ).observe(max(0.0, clock() - started))

        return async_wrapper

    @wraps(node)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = clock()
        status = "success"
        try:
            result = cast(Callable[P, R], node)(*args, **kwargs)
            if isinstance(result, dict) and result.get("error"):
                status = "error"
            return result
        except BaseException:
            status = "error"
            raise
        finally:
            metrics.graph_node_duration.labels(
                node=normalized_node,
                status=normalize_label(status, STATUSES),
            ).observe(max(0.0, clock() - started))

    return sync_wrapper


class InstrumentedSearchBackend:
    """Measure five independent domain searches without serializing them."""

    def __init__(self, backend: SearchBackend, metrics: MetricsRuntime, backend_mode: str) -> None:
        self._backend = backend
        self._metrics = metrics
        self._backend_mode = normalize_label(backend_mode, BACKENDS)

    async def _run(self, kind: SearchKindValue, operation: Awaitable[R]) -> R:
        started = time.monotonic()
        status = "success"
        try:
            return await operation
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except BaseException:
            status = "error"
            raise
        finally:
            labels = {
                "kind": normalize_label(kind, SEARCH_KINDS),
                "backend": self._backend_mode,
                "status": normalize_label(status, STATUSES),
            }
            self._metrics.search_tasks.labels(**labels).inc()
            self._metrics.search_duration.labels(**labels).observe(
                max(0.0, time.monotonic() - started)
            )

    async def search_flights(self, requirements: Any) -> Any:
        """Measure one flight search."""

        return await self._run("flights", self._backend.search_flights(requirements))

    async def search_hotels(self, requirements: Any) -> Any:
        """Measure one hotel search."""

        return await self._run("hotels", self._backend.search_hotels(requirements))

    async def search_attractions(self, requirements: Any) -> Any:
        """Measure one attraction search."""

        return await self._run("attractions", self._backend.search_attractions(requirements))

    async def get_weather(self, requirements: Any) -> Any:
        """Measure one weather search."""

        return await self._run("weather", self._backend.get_weather(requirements))

    async def get_route(self, origin: str, destination: str) -> Any:
        """Measure one route search."""

        return await self._run("route", self._backend.get_route(origin, destination))


class InstrumentedAdvancedRetriever:
    """Measure advanced RAG results without retaining query or context text."""

    def __init__(self, retriever: AdvancedRetriever, metrics: MetricsRuntime) -> None:
        self._retriever = retriever
        self._metrics = metrics

    async def retrieve(
        self,
        query_bundle: QueryBundle,
        *,
        top_k: int | None = None,
        mode: RetrievalMode = "hybrid_reranked",
        use_cache: bool = True,
    ) -> AdvancedRetrievalResult:
        """Delegate once and record only bounded diagnostics."""

        started = time.monotonic()
        status = "success"
        cache_status = "unavailable"
        contexts = 0
        try:
            result = await self._retriever.retrieve(
                query_bundle,
                top_k=top_k,
                mode=mode,
                use_cache=use_cache,
            )
            status = (
                "unavailable"
                if result.error == "rag_not_indexed"
                else "error"
                if result.error is not None
                else "success"
            )
            raw_cache_status = result.diagnostics.cache_status
            cache_status = raw_cache_status if raw_cache_status in CACHE_STATUSES else "unavailable"
            contexts = len(result.contexts)
            return result
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except BaseException:
            status = "error"
            raise
        finally:
            normalized_status = normalize_label(status, STATUSES)
            self._metrics.rag_searches.labels(
                status=normalized_status,
                cache_status=cache_status,
            ).inc()
            self._metrics.rag_duration.labels(status=normalized_status).observe(
                max(0.0, time.monotonic() - started)
            )
            self._metrics.rag_contexts.observe(contexts)
            self._metrics.rag_cache_events.labels(cache_status=cache_status).inc()


def record_finalization(metrics: MetricsRuntime, state: dict[str, Any]) -> None:
    """Record actual review state when the finalization node is reached."""

    review_status = normalize_label(state.get("review_status", "unknown"), REVIEW_STATUSES)
    reason = normalize_label(state.get("finalization_reason", "unknown"), FINALIZATION_REASONS)
    metrics.plan_finalizations.labels(review_status=review_status, reason=reason).inc()
    metrics.review_rounds.labels(final_status=review_status).observe(
        max(0, int(state.get("review_round", 0)))
    )
