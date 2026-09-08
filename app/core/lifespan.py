"""FastAPI lifespan wiring for application-owned resources."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace

from fastapi import FastAPI

from app.core.config import Settings
from app.core.persistence import (
    PersistenceFactory,
    create_postgres_persistence_resources,
)
from app.core.resources import (
    ResourceFactory,
    close_app_resources,
    create_app_resources,
)
from app.graphs.graph import TravelPlanningGraph, build_travel_planning_graph
from app.llm.runtime import create_llm_runtime
from app.observability.instrumentation import InstrumentedAdvancedRetriever
from app.observability.logging import configure_logging, log_event, shutdown_logging
from app.observability.metrics import MetricsRuntime

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_lifespan(
    settings: Settings,
    resource_factory: ResourceFactory = create_app_resources,
    persistence_factory: PersistenceFactory = create_postgres_persistence_resources,
    travel_graph: TravelPlanningGraph | None = None,
    metrics: MetricsRuntime | None = None,
) -> Lifespan:
    """Build a lifespan that owns infrastructure and persistence resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_metrics = metrics or app.state.metrics
        log_handler = configure_logging(settings.log_level)
        resources = None
        try:
            log_event(
                "application_starting", "Application resources are starting.", component="app"
            )
            resources = await resource_factory(settings)
            if resources.llm_runtime is None:
                resources.llm_runtime = create_llm_runtime(settings, runtime_metrics)
            if resources.duffel_runtime is not None:
                resources.duffel_runtime.client.metrics = runtime_metrics
            if resources.travel_runtime is not None:
                resources.travel_runtime.set_metrics(runtime_metrics)
            app.state.resources = resources
            advanced_retriever = None
            if resources.rag_runtime is not None:
                advanced_retriever = InstrumentedAdvancedRetriever(
                    resources.rag_runtime.retriever,
                    runtime_metrics,
                )
                resources.rag_runtime = replace(
                    resources.rag_runtime,
                    retriever=advanced_retriever,
                )
            if resources.mcp_runtime is not None:
                invoker = getattr(resources.mcp_runtime, "invoker", None)
                if invoker is not None:
                    invoker.metrics = runtime_metrics
            backend_mode = settings.travel_search_backend_mode
            app.state.travel_planning_graph = travel_graph or build_travel_planning_graph(
                advanced_retriever=advanced_retriever,
                search_backend=resources.search_backend,
                review_score_threshold=settings.review_score_threshold,
                review_max_rounds=settings.review_max_rounds,
                metrics=runtime_metrics,
                backend_mode=backend_mode,
                reasoning_mode=settings.agent_reasoning_mode,
                llm_provider=resources.llm_runtime.provider,
                allow_deterministic_fallback=settings.qwen_allow_deterministic_fallback,
            )
            try:
                persistence_context = persistence_factory(
                    settings,
                    advanced_retriever,
                    resources.search_backend,
                    runtime_metrics,
                    backend_mode,
                    settings.agent_reasoning_mode,
                    resources.llm_runtime.provider,
                    settings.qwen_allow_deterministic_fallback,
                )
            except TypeError:
                # Retain the narrow P07 test seam for a legacy two-argument failure double.
                persistence_context = persistence_factory(settings, advanced_retriever)
            async with persistence_context as persistence:
                app.state.persistence = persistence
                log_event("application_ready", "Application resources are ready.", component="app")
                try:
                    yield
                finally:
                    del app.state.persistence
        finally:
            try:
                if resources is not None:
                    await close_app_resources(resources)
            finally:
                if hasattr(app.state, "travel_planning_graph"):
                    del app.state.travel_planning_graph
                if hasattr(app.state, "resources"):
                    del app.state.resources
                log_event("application_stopped", "Application resources stopped.", component="app")
                await shutdown_logging(log_handler)

    return lifespan
