"""No-cost status and readiness tests for both reasoning modes."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.routes import readiness as readiness_module
from app.core.config import Settings
from app.core.resources import AppResources
from app.llm.diagnostics import LLMRuntimeDiagnostics
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.runtime import LLMRuntime
from app.main import create_app
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


@contextmanager
def client_for(
    settings: Settings,
    runtime: LLMRuntime | None = None,
) -> Iterator[TestClient]:
    """Yield an app using only local infrastructure and optional fake LLM resources."""

    fakes = make_resource_fakes(settings)
    fakes.resources.llm_runtime = runtime

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(application) as client:
        yield client


def test_deterministic_status_is_safe_and_requires_no_key() -> None:
    with client_for(Settings(_env_file=None)) as client:
        response = client.get("/api/v1/llm/status")

    assert response.status_code == 200
    assert response.json() == {
        "reasoning_mode": "deterministic",
        "provider": "none",
        "configured": False,
        "model": "qwen-plus",
        "base_url_region_or_host_class": "china-beijing",
        "fallback_enabled": False,
    }
    assert "key" not in response.text.casefold()


def test_qwen_status_reads_cached_diagnostics_without_calling_provider() -> None:
    settings = Settings(
        _env_file=None,
        agent_reasoning_mode="qwen",
        qwen_api_key=SecretStr("not-a-real-key"),
    )
    provider = FakeStructuredLLMProvider()
    runtime = LLMRuntime(
        provider=provider,
        diagnostics=LLMRuntimeDiagnostics(
            reasoning_mode="qwen",
            provider="qwen",
            configured=True,
            model="qwen-plus",
            base_url_host_class="china-beijing",
            fallback_enabled=False,
        ),
    )
    with client_for(settings, runtime) as client:
        response = client.get("/api/v1/llm/status")

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert provider.plan_inputs == []
    assert provider.review_inputs == []


def test_qwen_missing_key_makes_readiness_503_but_health_stays_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness_module, "check_postgres", AsyncMock(return_value=None))
    monkeypatch.setattr(readiness_module, "check_redis", AsyncMock(return_value=None))
    settings = Settings(
        _env_file=None,
        agent_reasoning_mode="qwen",
        qwen_api_key=SecretStr(""),
    )
    with client_for(settings) as client:
        ready = client.get("/ready")
        health = client.get("/health")

    assert ready.status_code == 503
    assert ready.json()["services"]["qwen"] == {"status": "error"}
    assert health.status_code == 200
