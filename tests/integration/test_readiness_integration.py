"""Opt-in integration test against the running P01 Docker services."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to check local Docker infrastructure",
)
def test_readiness_against_docker_services() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "ready",
        "services": {
            "postgresql": {"status": "ok"},
            "redis": {"status": "ok"},
            "chroma": {"status": "ok"},
        },
    }
