"""Configuration and HTTP hardening without cloud accounts."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def production(**updates):
    values = dict(
        _env_file=None,
        app_env="production",
        auth_mode="auth0",
        auth0_issuer="https://tenant.example",
        auth0_audience="https://api.example",
        api_docs_enabled=False,
        metrics_enabled=False,
        cors_allowed_origins=["https://frontend.example"],
        trusted_hosts=["api.example", "healthcheck.railway.app", "testserver"],
        postgres_password="unit-only-db-password",
        redis_password="unit-only-redis-password",
    )
    values.update(updates)
    return Settings(**values)


@pytest.mark.parametrize(
    "updates",
    [
        {"auth_mode": "demo"},
        {"auth0_issuer": ""},
        {"auth0_audience": ""},
        {"auth0_issuer": "http://tenant.example"},
        {"auth0_issuer": "https://user:pass@tenant.example"},
        {"auth0_issuer": "https://tenant.example/path"},
        {"auth0_issuer": "https://tenant.example/#fragment"},
        {"auth0_issuer": "https://127.0.0.1"},
        {"auth0_issuer": "https://tenant.example?query=x"},
        {"cors_allowed_origins": ["*"]},
        {"cors_allowed_origins": ["http://localhost:5173"]},
        {"trusted_hosts": ["*"]},
        {"api_docs_enabled": True},
        {"metrics_enabled": True},
        {"postgres_password": "travel_dev_only"},
        {"redis_password": ""},
        {"agent_reasoning_mode": "qwen"},
        {"travel_data_mode": "external"},
        {"auth_rate_plan_per_day": 0},
        {"auth_rate_global_plan_per_day": 0},
    ],
)
def test_unsafe_production_settings_rejected(updates):
    with pytest.raises(ValueError):
        production(**updates)


def test_safe_settings_and_docs_metrics_policy():
    settings = production()
    assert settings.auth0_issuer == "https://tenant.example/"
    client = TestClient(create_app(settings=settings))
    for path in ("/docs", "/redoc", "/openapi.json", "/metrics"):
        assert client.get(path).status_code == 404
    assert client.get("/health", headers={"Host": "healthcheck.railway.app"}).status_code == 200
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400


@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("https://frontend.example", True),
        ("https://attacker.example", False),
    ],
)
def test_cors_and_security_headers(origin, allowed):
    client = TestClient(create_app(settings=production()))
    response = client.options(
        "/api/v1/agents/plans",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type,X-Request-ID",
        },
    )
    assert response.status_code == (200 if allowed else 400)
    assert ("access-control-allow-origin" in response.headers) is allowed
    assert "access-control-allow-credentials" not in response.headers
    health = client.get("/health", headers={"Origin": origin})
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    if allowed:
        assert "X-Request-ID" in health.headers["access-control-expose-headers"]


def test_local_cors_remains_usable():
    client = TestClient(create_app(settings=Settings(_env_file=None)))
    for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin
