"""Tests for liveness endpoints that must not probe infrastructure."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from tests.helpers import make_resource_fakes


@pytest.mark.parametrize("path", ["/health", "/health/live"])
def test_health_does_not_contact_external_services(path: str) -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    app = create_app(settings=settings, resource_factory=resource_factory)
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-travel-planner",
    }
    assert fakes.chroma.heartbeat_calls == 0
    assert fakes.chroma.close_calls == 1
    assert fakes.redis.close_calls == 1
    assert fakes.engine.dispose_calls == 1
