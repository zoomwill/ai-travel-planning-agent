"""Container checker mechanics without starting Docker from ordinary pytest."""

from types import SimpleNamespace

import httpx
import pytest

from scripts import check_deployment as checker


def test_host_port_reloaded_after_restart(monkeypatch):
    responses = iter(['{"8080/tcp":[{"HostPort":"41001"}]}', '{"8080/tcp":[{"HostPort":"41002"}]}'])
    monkeypatch.setattr(checker, "docker", lambda *args: next(responses))
    assert checker.published_port("test") == 41001
    assert checker.published_port("test") == 41002


def test_readiness_deadline_and_success(monkeypatch):
    clock = iter([0, 1, 181])
    monkeypatch.setattr(checker.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(checker.time, "sleep", lambda _: None)
    client = SimpleNamespace(get=lambda *args, **kwargs: httpx.Response(503))
    with pytest.raises(RuntimeError, match="readiness deadline"):
        checker.wait_ready(client)
    monkeypatch.setattr(checker.time, "monotonic", lambda: 0)
    client.get = lambda *args, **kwargs: httpx.Response(200)
    checker.wait_ready(client)
