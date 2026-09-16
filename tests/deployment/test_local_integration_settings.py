"""Local integration overrides remote process configuration without editing .env."""

from app.core.config import Settings
from tests.local_infrastructure import isolate_local_infrastructure


def test_remote_targets_and_real_provider_modes_are_replaced(monkeypatch):
    for key in ("POSTGRES_HOST", "REDIS_HOST", "CHROMA_HOST"):
        monkeypatch.setenv(key, "production.example")
    monkeypatch.setenv("AUTH_MODE", "auth0")
    monkeypatch.setenv("AGENT_REASONING_MODE", "qwen")
    monkeypatch.setenv("TRAVEL_DATA_MODE", "external")
    for key in ("QWEN_API_KEY", "DUFFEL_ACCESS_TOKEN", "LITEAPI_API_KEY"):
        monkeypatch.setenv(key, "synthetic-never-a-provider-secret")
    isolate_local_infrastructure(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.postgres_host == settings.redis_host == settings.chroma_host == "127.0.0.1"
    assert settings.auth_mode == "demo" and settings.agent_reasoning_mode == "deterministic"
    assert settings.selected_flight_provider == settings.selected_hotel_provider == "demo"
    assert not settings.qwen_is_configured
    assert not settings.duffel_is_configured and not settings.liteapi_is_configured
