"""A verifier shutdown failure must not leak the application's other resource pools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


def test_verifier_close_failure_still_closes_resources(monkeypatch, auth_settings):
    verifier = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("test close failure")))
    monkeypatch.setattr("app.core.lifespan.TokenVerifier", lambda _: verifier)
    fakes = make_resource_fakes(auth_settings)

    async def resource_factory(_):
        return fakes.resources

    app = create_app(
        settings=auth_settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with pytest.raises(RuntimeError, match="test close failure"), TestClient(app):
        pass
    verifier.aclose.assert_awaited_once()
    assert fakes.chroma.close_calls == 1
    assert fakes.redis.close_calls == 1
    assert fakes.engine.dispose_calls == 1
