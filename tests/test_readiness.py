"""Unit tests for concurrent, sanitized readiness reporting."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import readiness as readiness_module
from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from tests.helpers import FakeChroma, make_resource_fakes


def make_client(
    settings: Settings,
    chroma: FakeChroma | None = None,
) -> tuple[TestClient, AppResources]:
    """Create a client backed only by local test doubles."""

    fakes = make_resource_fakes(settings, chroma=chroma)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    return TestClient(
        create_app(settings=settings, resource_factory=resource_factory)
    ), fakes.resources


def test_ready_when_every_probe_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    postgres_probe = AsyncMock(return_value=None)
    redis_probe = AsyncMock(return_value=None)
    monkeypatch.setattr(readiness_module, "check_postgres", postgres_probe)
    monkeypatch.setattr(readiness_module, "check_redis", redis_probe)
    client, _ = make_client(Settings(_env_file=None))

    with client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "services": {
            "postgresql": {"status": "ok"},
            "redis": {"status": "ok"},
            "chroma": {"status": "ok"},
        },
    }
    postgres_probe.assert_awaited_once()
    redis_probe.assert_awaited_once()


def test_failure_keeps_all_service_states_and_hides_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_secret = "not-a-real-password"
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(
        readiness_module,
        "check_redis",
        AsyncMock(side_effect=RuntimeError(f"connection failed: {fake_secret}")),
    )
    client, _ = make_client(Settings(_env_file=None))

    with client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "services": {
            "postgresql": {"status": "ok"},
            "redis": {"status": "error"},
            "chroma": {"status": "ok"},
        },
    }
    assert fake_secret not in response.text
    assert "connection failed" not in response.text


def test_timeout_returns_503_without_hiding_other_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, infrastructure_timeout_seconds=0.01)
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock(return_value=None))
    client, _ = make_client(settings, FakeChroma(heartbeat_delay=0.2))

    with client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["services"] == {
        "postgresql": {"status": "ok"},
        "redis": {"status": "ok"},
        "chroma": {"status": "error"},
    }


@pytest.mark.asyncio
async def test_run_probe_converts_exception_to_safe_status() -> None:
    async def failing_probe() -> None:
        raise OSError("private connection detail")

    assert await readiness_module.run_probe(failing_probe, timeout_seconds=1) == "error"
