"""Repeat startup without destructive index cleanup or a live database."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.deployment import bootstrap as module
from app.deployment.bootstrap import missing_ids
from app.deployment.start import port_number


def test_missing_ids_non_destructive_policy():
    assert missing_ids([], ["a", "b"]) == {"a", "b"}
    assert missing_ids(["a"], ["a", "b"]) == {"b"}
    assert missing_ids(["a", "b"], ["a", "b"]) == set()
    with pytest.raises(ValueError):
        missing_ids(["unexpected"], ["a"])


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_bad_port_rejected(value):
    with pytest.raises(ValueError):
        port_number(value)


@pytest.mark.asyncio
async def test_bootstrap_twice_preserves_index(monkeypatch, tmp_path):
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    monkeypatch.setattr(module.AsyncConnection, "connect", AsyncMock(return_value=connection))
    setup_calls = []

    @asynccontextmanager
    async def persistence(*args, **kwargs):
        setup = AsyncMock()
        setup_calls.append(setup)
        yield SimpleNamespace(setup=setup)

    monkeypatch.setattr(module.AsyncPostgresSaver, "from_conn_string", persistence)
    monkeypatch.setattr(module.AsyncPostgresStore, "from_conn_string", persistence)
    monkeypatch.setattr(
        module.SentenceTransformerEmbeddingBackend,
        "load",
        lambda *args, **kwargs: SimpleNamespace(dimensions=384),
    )

    class Vector:
        def __init__(self):
            self.ids = set()
            self.upserts = 0

        def existing_ids(self, **kwargs):
            return self.ids.copy()

        def upsert_children(self, children):
            self.ids.update(child.child_id for child in children)
            self.upserts += 1

        def count(self):
            return len(self.ids)

    vector = Vector()
    monkeypatch.setattr(module, "create_advanced_vector_store", lambda *args: vector)
    redis = AsyncMock()
    monkeypatch.setattr(module, "create_redis_client", lambda _: redis)
    parent_store = SimpleNamespace(put_many=AsyncMock())
    monkeypatch.setattr(
        module.RedisParentDocumentStore, "from_redis", lambda *args, **kwargs: parent_store
    )
    monkeypatch.setattr("app.rag.manifest.GENERATED_RAG_ROOT", tmp_path)
    settings = Settings(_env_file=None)
    await module.bootstrap(settings)
    first = {p.name: p.read_bytes() for p in (tmp_path / "advanced-v1").iterdir()}
    await module.bootstrap(settings)
    second = {p.name: p.read_bytes() for p in (tmp_path / "advanced-v1").iterdir()}
    assert first == second
    assert vector.upserts == 1
    assert len(setup_calls) == 4 and all(call.await_count == 1 for call in setup_calls)
    assert parent_store.put_many.await_count == 2
    assert redis.aclose.await_count == 2
    assert all(
        "DROP" not in str(call) and "TRUNCATE" not in str(call)
        for call in connection.execute.call_args_list
    )
