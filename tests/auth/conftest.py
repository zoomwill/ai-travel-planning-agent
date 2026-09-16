"""Generated RSA keys never leave the test process."""

import json
import time
from datetime import date, timedelta
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.tokens import TokenVerifier
from app.core.config import Settings
from app.llm.diagnostics import LLMRuntimeDiagnostics
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.runtime import LLMRuntime
from app.main import create_app
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.intake.test_api import complete_extraction


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="test-key", use="sig", alg="RS256")
    return private, jwk


@pytest.fixture
def auth_settings():
    return Settings(
        _env_file=None,
        auth_mode="auth0",
        auth0_issuer="https://tenant.example/",
        auth0_audience="https://travel-api.example",
    )


@pytest.fixture
def token(keys, auth_settings):
    def make(subject="auth0|user-a", **overrides):
        claims = dict(
            sub=subject,
            iss=auth_settings.auth0_issuer,
            aud=auth_settings.auth0_audience,
            exp=int(time.time()) + 600,
        )
        claims.update(overrides)
        return jwt.encode(claims, keys[0], algorithm="RS256", headers={"kid": "test-key"})

    return make


@pytest.fixture
def auth_persistence_factory():
    return make_in_memory_persistence_factory()


@pytest.fixture
def auth_client(monkeypatch, keys, auth_settings, auth_persistence_factory):
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, json={"keys": [keys[1]]})

    monkeypatch.setattr(
        "app.core.lifespan.TokenVerifier",
        lambda settings: TokenVerifier(settings, transport=httpx.MockTransport(serve)),
    )
    fakes = make_resource_fakes(auth_settings)
    fakes.resources.redis_client.eval = AsyncMock(return_value=0)
    provider = FakeStructuredLLMProvider(
        intake_extractions=[
            complete_extraction(start_date=date.today() + timedelta(days=30), destination=city)
            for city in ("Tokyo", "Paris", "London")
        ]
    )
    fakes.resources.llm_runtime = LLMRuntime(
        provider=provider,
        diagnostics=LLMRuntimeDiagnostics(
            reasoning_mode="qwen",
            provider="qwen",
            configured=True,
            model="fake-qwen",
            base_url_host_class="china-beijing",
            fallback_enabled=False,
        ),
    )

    async def resources(_):
        return fakes.resources

    app = create_app(
        settings=auth_settings,
        resource_factory=resources,
        persistence_factory=auth_persistence_factory,
    )
    with TestClient(app) as client:
        yield client, fakes, requests
