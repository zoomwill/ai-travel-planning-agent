"""Test-process safety settings applied before test modules import LangGraph."""

import os

import httpx
import pytest

from tests.local_infrastructure import isolate_local_infrastructure

os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
os.environ["TRAVEL_DATA_MODE"] = "demo"
os.environ["AGENT_REASONING_MODE"] = "deterministic"
if os.environ.get("RUN_AUTH0_INTEGRATION_TESTS") != "1":
    # Local Auth0 configuration must not change ordinary, token-free integration fixtures.
    os.environ["AUTH_MODE"] = "demo"


@pytest.fixture(autouse=True)
def local_integration_environment(request, monkeypatch):
    """Marked local integration must never inherit remote hosts or provider modes."""
    if request.node.get_closest_marker("integration") is not None:
        isolate_local_infrastructure(monkeypatch)


@pytest.fixture(autouse=True)
def forbid_ungated_provider_internet(request, monkeypatch):
    """MockTransport stays usable; real HTTP transports require separate provider gates."""
    original = httpx.AsyncHTTPTransport.handle_async_request
    original_sync = httpx.HTTPTransport.handle_request
    local_only = request.node.get_closest_marker("integration") is not None
    gates = {
        "api.duffel.com": "RUN_DUFFEL_INTEGRATION_TESTS",
        "api.liteapi.travel": "RUN_LITEAPI_INTEGRATION_TESTS",
    }

    def check(request):
        if local_only and request.url.host not in {"127.0.0.1", "localhost", "::1"}:
            raise AssertionError("Local integration HTTP transport must use a loopback host")
        gate = gates.get(request.url.host)
        if request.url.host.endswith(".aliyuncs.com"):
            gate = "RUN_LLM_INTEGRATION_TESTS"
        if request.url.path.endswith("/.well-known/jwks.json") or request.url.host.endswith(
            ".auth0.com"
        ):
            gate = "RUN_AUTH0_INTEGRATION_TESTS"
        if gate is not None and os.environ.get(gate) != "1":
            raise AssertionError("Real external transport requires its explicit test gate")

    async def guarded(self, request):
        check(request)
        return await original(self, request)

    def guarded_sync(self, request):
        check(request)
        return original_sync(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
