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


def test_fresh_bootstrap_requires_all_batches_and_release():
    lines = ["BOOTSTRAP stage=chroma_existing_ids_ready children=77 batches=10"]
    for index, count in enumerate([8] * 9 + [5], start=1):
        for stage in ("chroma_index_batch_start", "chroma_index_batch_complete"):
            lines.append(f"BOOTSTRAP stage={stage} batch={index} batches=10 children={count}")
    lines.extend(
        [
            "BOOTSTRAP stage=chroma_ready children=77",
            "BOOTSTRAP stage=memory_released",
            "BOOTSTRAP stage=complete",
        ]
    )
    logs = "\n".join(lines)
    assert checker.fresh_batch_counts(logs) == [8] * 9 + [5]
    for broken in (
        logs.replace("children=77", "children=76"),
        logs + "\n" + lines[1],
        logs.replace("BOOTSTRAP stage=memory_released", ""),
    ):
        with pytest.raises(RuntimeError):
            checker.fresh_batch_counts(broken)


def test_memory_peak_never_fabricates(monkeypatch):
    monkeypatch.setattr(checker, "docker", lambda *args: "123456")
    assert checker.memory_peak("test") == 123456
    monkeypatch.setattr(checker, "docker", lambda *args: "not-available")
    assert checker.memory_peak("test") is None


def test_exited_container_fails_before_waiting_on_http():
    client = SimpleNamespace(get=lambda *args, **kwargs: pytest.fail("HTTP must not run"))
    with pytest.raises(RuntimeError, match="exited before readiness"):
        checker.wait_ready(client, alive=lambda: False)
