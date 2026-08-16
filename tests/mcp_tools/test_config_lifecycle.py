"""Settings and startup-failure safety tests for P11 MCP mode."""

import sys

import pytest
from pydantic import ValidationError

from app.core import resources as resources_module
from app.core.config import Settings
from app.core.resources import close_app_resources, create_app_resources
from app.mcp_tools.backend import UnavailableMCPTravelSearchBackend
from app.mcp_tools.client import build_mcp_client
from app.rag.runtime import AdvancedRagRuntime
from tests.helpers import FakeChroma, FakeEngine, FakeRedis


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:9001/mcp",
        "http://example.com:9001/mcp",
        "http://127.0.0.1:9002/mcp",
        "http://127.0.0.1:9001/wrong",
        "http://user:password@127.0.0.1:9001/mcp",
        "http://127.0.0.1:9001/mcp?token=secret",
    ],
)
def test_settings_reject_nonlocal_or_mismatched_mcp_url(url: str) -> None:
    with pytest.raises(ValidationError, match="mcp_http_url"):
        Settings(_env_file=None, mcp_http_url=url)


def test_client_uses_fixed_python_module_and_minimal_safe_environment() -> None:
    client = build_mcp_client(Settings(_env_file=None))
    stdio = client.connections["local_tools"]
    http = client.connections["travel_tools"]

    assert stdio["command"] == sys.executable
    assert stdio["args"] == ["-m", "app.mcp_tools.servers.local_stdio"]
    assert stdio["env"] == {"PYTHONUNBUFFERED": "1"}
    assert http["transport"] == "http"
    assert "headers" not in http
    assert all(
        secret not in repr(client.connections).casefold()
        for secret in ("password", "token", "postgres", "redis")
    )


@pytest.mark.asyncio
async def test_mcp_discovery_failure_does_not_abort_resource_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    redis = FakeRedis()
    chroma = FakeChroma()

    async def no_rag_runtime(*args) -> AdvancedRagRuntime | None:
        del args
        return None

    async def fail_mcp_runtime(_: Settings):
        raise RuntimeError("private MCP startup detail")

    monkeypatch.setattr(resources_module, "create_postgres_engine", lambda _: engine)
    monkeypatch.setattr(resources_module, "create_redis_client", lambda _: redis)
    monkeypatch.setattr(resources_module, "ChromaClientProvider", lambda _: chroma)
    monkeypatch.setattr(resources_module, "create_advanced_rag_runtime", no_rag_runtime)
    monkeypatch.setattr(resources_module, "create_mcp_runtime", fail_mcp_runtime)

    resources = await create_app_resources(
        Settings(_env_file=None, travel_search_backend_mode="mcp")
    )

    assert resources.mcp_runtime is None
    assert isinstance(resources.search_backend, UnavailableMCPTravelSearchBackend)
    await close_app_resources(resources)
    assert engine.dispose_calls == redis.close_calls == chroma.close_calls == 1
