"""No-cost status, readiness, configuration, and pre-stream boundary tests."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes import readiness as readiness_module
from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


def _client(settings: Settings) -> TestClient:
    fakes = make_resource_fakes(settings)

    async def factory(_: Settings) -> AppResources:
        return fakes.resources

    return TestClient(
        create_app(
            settings=settings,
            resource_factory=factory,
            persistence_factory=make_in_memory_persistence_factory(),
        )
    )


def test_demo_and_duffel_status_are_local_and_secret_free() -> None:
    with _client(Settings(_env_file=None)) as client:
        demo = client.get("/api/v1/travel-data/status")
    assert demo.json() == {
        "mode": "demo",
        "provider": "deterministic_demo",
        "configured": True,
        "environment": None,
        "external_kinds": [],
        "demo_kinds": ["flights", "hotels", "attractions", "weather", "route"],
        "fallback_enabled": False,
        "stays_access_state": "not_applicable",
        "flight_provider": "demo",
        "flight_environment": None,
        "flight_configured": True,
        "hotel_provider": "demo",
        "hotel_environment": None,
        "hotel_configured": True,
        "flight_fallback_enabled": False,
        "hotel_fallback_enabled": False,
        "location_provider": "not_required",
    }

    settings = Settings(
        _env_file=None,
        travel_data_mode="duffel",
        duffel_access_token="duffel_test_unit_only",
    )
    with _client(settings) as client:
        response = client.get("/api/v1/travel-data/status")
    body = response.json()
    assert body["configured"] is True
    assert body["external_kinds"] == ["flights", "hotels"]
    assert "token" not in response.text.casefold()
    assert "unit_only" not in response.text


def test_fixed_host_and_environment_consistency_are_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, duffel_api_base_url="https://example.com")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, duffel_env="test", duffel_access_token="live-looking-token")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            duffel_env="live",
            duffel_access_token="duffel_test_unit_only",
        )


def test_demo_status_reports_the_configured_fallback_flag_without_remote_probe() -> None:
    settings = Settings(_env_file=None, duffel_allow_demo_fallback=True)

    with _client(settings) as client:
        response = client.get("/api/v1/travel-data/status")

    assert response.status_code == 200
    assert response.json()["fallback_enabled"] is True


def test_duffel_missing_token_changes_ready_not_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock(return_value=None))
    settings = Settings(_env_file=None, travel_data_mode="duffel")
    with _client(settings) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        stream = client.post(
            "/api/v1/agents/threads/duffel-missing/plans/stream",
            json={
                "user_id": "unit-user",
                "requirements": {
                    "origin": "Cleveland",
                    "destination": "Tokyo",
                    "start_date": "2027-04-10",
                    "end_date": "2027-04-12",
                    "budget": "5000",
                    "currency": "USD",
                    "travelers": 1,
                    "preferences": [],
                },
                "remember_preferences": [],
            },
        )

    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["services"]["duffel"] == {"status": "error"}
    assert stream.status_code == 503
    assert stream.json()["detail"]["code"] == "duffel_not_configured"
