"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes.agent_plans import router as agent_plans_router
from app.api.routes.health import router as health_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.persistence import router as persistence_router
from app.api.routes.plans import router as plans_router
from app.api.routes.rag import router as rag_router
from app.api.routes.readiness import router as readiness_router
from app.core.config import Settings, get_settings
from app.core.lifespan import create_lifespan
from app.core.persistence import (
    PersistenceFactory,
    create_postgres_persistence_resources,
)
from app.core.resources import ResourceFactory, create_app_resources
from app.graphs.graph import TravelPlanningGraph, build_travel_planning_graph


def create_app(
    *,
    settings: Settings | None = None,
    resource_factory: ResourceFactory = create_app_resources,
    persistence_factory: PersistenceFactory = create_postgres_persistence_resources,
    travel_graph: TravelPlanningGraph | None = None,
) -> FastAPI:
    """Create a FastAPI application with injectable lifespan resources."""

    resolved_settings = settings or get_settings()
    resolved_travel_graph = travel_graph or build_travel_planning_graph(
        review_score_threshold=resolved_settings.review_score_threshold,
        review_max_rounds=resolved_settings.review_max_rounds,
    )
    application = FastAPI(
        title="AI Intelligent Travel Planning System",
        version="0.1.0",
        lifespan=create_lifespan(
            resolved_settings,
            resource_factory,
            persistence_factory,
            travel_graph,
        ),
    )
    application.state.settings = resolved_settings
    application.state.travel_planning_graph = resolved_travel_graph
    application.include_router(agent_plans_router)
    application.include_router(health_router)
    application.include_router(mcp_router)
    application.include_router(readiness_router)
    application.include_router(plans_router)
    application.include_router(persistence_router)
    application.include_router(rag_router)
    return application


app = create_app()
