"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI Intelligent Travel Planning System",
    version="0.1.0",
)
app.include_router(health_router)
