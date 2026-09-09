"""Safe failure classification and bootstrap-before-runtime entry point ordering."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.deployment import start
from app.deployment.diagnostics import DeploymentFailure, bootstrap_stage


@pytest.mark.parametrize("phase", ["settings", "bootstrap", "application", "uvicorn"])
def test_startup_failure_reports_phase_and_class_only(monkeypatch, capsys, phase):
    secret = "postgresql://private:unit-secret@example.invalid/database"

    def fail(*args, **kwargs):
        raise ConnectionError(secret)

    monkeypatch.setattr(
        start, "Settings", fail if phase == "settings" else lambda: Settings(_env_file=None)
    )
    monkeypatch.setattr(
        start,
        "bootstrap",
        AsyncMock(side_effect=ConnectionError(secret) if phase == "bootstrap" else None),
    )
    monkeypatch.setattr(
        "app.main.create_app", fail if phase == "application" else lambda **kw: object()
    )
    monkeypatch.setattr(start.uvicorn, "Config", lambda *a, **kw: object())
    monkeypatch.setattr(
        start.uvicorn,
        "Server",
        lambda *a: SimpleNamespace(serve=AsyncMock(side_effect=ConnectionError(secret))),
    )
    assert start.main() == 1
    assert (
        capsys.readouterr().out
        == f"FAIL deployment startup phase={phase} error_type=ConnectionError\n"
    )


@pytest.mark.asyncio
async def test_runtime_begins_only_after_bootstrap_returns(monkeypatch):
    events = []

    async def bootstrap(_):
        events.append("bootstrap")
        await asyncio.sleep(0)
        events.append("released")

    def app(**kwargs):
        assert events == ["bootstrap", "released"]
        events.append("app")
        return object()

    monkeypatch.setattr(start, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(start, "bootstrap", bootstrap)
    monkeypatch.setattr("app.main.create_app", app)
    monkeypatch.setattr(start.uvicorn, "Config", lambda *a, **kw: object())
    serve = AsyncMock()
    monkeypatch.setattr(start.uvicorn, "Server", lambda *a: SimpleNamespace(serve=serve))
    await start.serve()
    serve.assert_awaited_once()
    assert events == ["bootstrap", "released", "app"]


@pytest.mark.asyncio
async def test_cancellation_is_not_a_normal_failure(monkeypatch):
    monkeypatch.setattr(start, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(start, "bootstrap", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await start.serve()


def test_only_allowed_diagnostic_fields(monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: calls.append((args, kwargs)))
    for stage, counts in [
        ("raw-secret", {}),
        ("complete", {"password": 1}),
        ("complete", {"children": -1}),
        ("complete", {"batch": True}),
        ("complete", {"batches": 1_000_001}),
    ]:
        with pytest.raises(ValueError):
            bootstrap_stage(stage, **counts)
    assert calls == []
    error = DeploymentFailure("bootstrap", ValueError("private-message"))
    error.report()
    assert calls == [
        (("FAIL deployment startup phase=bootstrap error_type=ValueError",), {"flush": True})
    ]
