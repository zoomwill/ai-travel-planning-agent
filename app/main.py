"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes.agent_plans import router as agent_plans_router
from app.api.routes.health import router as health_router
from app.api.routes.plans import router as plans_router
from app.api.routes.readiness import router as readiness_router
from app.core.config import Settings, get_settings
from app.core.lifespan import create_lifespan
from app.core.resources import ResourceFactory, create_app_resources
from app.graphs.graph import TravelPlanningGraph, travel_planning_graph


def create_app(
    *,
    settings: Settings | None = None,
    resource_factory: ResourceFactory = create_app_resources,
    travel_graph: TravelPlanningGraph = travel_planning_graph,
) -> FastAPI:
    """Create a FastAPI application with injectable lifespan resources."""

    resolved_settings = settings or get_settings()
    application = FastAPI(
        title="AI Intelligent Travel Planning System",
        version="0.1.0",
        lifespan=create_lifespan(resolved_settings, resource_factory),
    )
    application.state.settings = resolved_settings
    application.state.travel_planning_graph = travel_graph
    application.include_router(agent_plans_router)
    application.include_router(health_router)
    application.include_router(readiness_router)
    application.include_router(plans_router)
    return application


app = create_app()
