"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.types import ASGIApp

from app.api.routes.agent_plans import router as agent_plans_router
from app.api.routes.conversation import router as conversation_router
from app.api.routes.health import router as health_router
from app.api.routes.llm import router as llm_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.persistence import router as persistence_router
from app.api.routes.plans import router as plans_router
from app.api.routes.rag import router as rag_router
from app.api.routes.readiness import router as readiness_router
from app.api.routes.travel_data import router as travel_data_router
from app.core.config import Settings, get_settings
from app.core.lifespan import create_lifespan
from app.core.persistence import (
    PersistenceFactory,
    create_postgres_persistence_resources,
)
from app.core.resources import ResourceFactory, create_app_resources
from app.graphs.graph import TravelPlanningGraph, build_travel_planning_graph
from app.observability.logging import log_event
from app.observability.metrics import MetricsRuntime
from app.observability.middleware import ObservabilityMiddleware


class ObservedFastAPI(FastAPI):
    """Place observability outside FastAPI's final safe error-response layer."""

    _observability_metrics: MetricsRuntime

    def build_middleware_stack(self) -> ASGIApp:
        """Observe completed 500 responses while preserving exception re-raise."""

        return ObservabilityMiddleware(
            super().build_middleware_stack(),
            metrics=self._observability_metrics,
        )


def create_app(
    *,
    settings: Settings | None = None,
    resource_factory: ResourceFactory = create_app_resources,
    persistence_factory: PersistenceFactory = create_postgres_persistence_resources,
    travel_graph: TravelPlanningGraph | None = None,
) -> FastAPI:
    """Create a FastAPI application with injectable lifespan resources."""

    resolved_settings = settings or get_settings()
    metrics = MetricsRuntime.create()
    resolved_travel_graph = travel_graph or build_travel_planning_graph(
        review_score_threshold=resolved_settings.review_score_threshold,
        review_max_rounds=resolved_settings.review_max_rounds,
        metrics=metrics,
        backend_mode=resolved_settings.travel_search_backend_mode,
        reasoning_mode=resolved_settings.agent_reasoning_mode,
        allow_deterministic_fallback=resolved_settings.qwen_allow_deterministic_fallback,
    )
    application = ObservedFastAPI(
        title="AI Intelligent Travel Planning System",
        version="0.1.0",
        lifespan=create_lifespan(
            resolved_settings,
            resource_factory,
            persistence_factory,
            travel_graph,
            metrics,
        ),
    )
    application._observability_metrics = metrics
    application.state.settings = resolved_settings
    application.state.metrics = metrics
    application.state.travel_planning_graph = resolved_travel_graph

    @application.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        """Expose this process's in-memory registry without probing dependencies."""

        return Response(
            content=generate_latest(metrics.registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
        """Return a stable 500 body while the middleware records and re-raises failures."""

        log_event(
            "unhandled_http_error",
            "An unhandled HTTP error was converted to a safe response.",
            component="http",
            error_code="internal_server_error",
            outcome="error",
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "internal_server_error",
                    "message": "The server could not complete the request.",
                }
            },
        )

    application.include_router(agent_plans_router)
    application.include_router(conversation_router)
    application.include_router(health_router)
    application.include_router(llm_router)
    application.include_router(mcp_router)
    application.include_router(readiness_router)
    application.include_router(plans_router)
    application.include_router(persistence_router)
    application.include_router(rag_router)
    application.include_router(travel_data_router)
    return application


app = create_app()
