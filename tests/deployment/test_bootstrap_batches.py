"""Bounded first indexing, partial recovery, safe output and startup-only model lifetime."""

import weakref
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.deployment import bootstrap as module
from app.rag.advanced_vector_store import AdvancedChromaVectorStore
from app.rag.embeddings import DeterministicHashEmbeddingBackend


@pytest.mark.parametrize("value", [0, -1, 33, "bad", "1.5", None, True, 1.0])
def test_bad_batch_rejected(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, rag_bootstrap_batch_size=value)


@pytest.mark.parametrize("value", [1, 8, 32, "8"])
def test_batch_setting_boundaries(value):
    assert Settings(_env_file=None, rag_bootstrap_batch_size=value).rag_bootstrap_batch_size == int(
        value
    )
    assert Settings(_env_file=None).rag_bootstrap_batch_size == 8


class RecordingCollection:
    """Record the real adapter's IDs, documents, metadata and offline vectors, in memory only."""

    def __init__(self):
        self.rows = {}
        self.batches = []
        self.fail_batch = None
        self.wrong_count = False

    def upsert(self, **kwargs):
        if self.fail_batch == len(self.batches) + 1:
            raise ConnectionError("private password and document contents must not be logged")
        self.batches.append(tuple(kwargs["ids"]))
        for index, child_id in enumerate(kwargs["ids"]):
            self.rows[child_id] = {
                field: kwargs[field][index] for field in ("documents", "metadatas", "embeddings")
            }

    def get(self, **kwargs):
        return {"ids": list(self.rows)}

    def count(self):
        return len(self.rows) + int(self.wrong_count)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, postgres_password="unit-only-sensitive-password")
    corpus = module.build_advanced_corpus(settings, embedding_dimension=384)
    assert len(corpus.children) == 77
    reference = RecordingCollection()
    AdvancedChromaVectorStore(
        reference, DeterministicHashEmbeddingBackend(384), metadata_filter_fallback=True
    ).upsert_children(corpus.children)
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    monkeypatch.setattr(module.AsyncConnection, "connect", AsyncMock(return_value=connection))

    @asynccontextmanager
    async def persistence(*args, **kwargs):
        yield SimpleNamespace(setup=AsyncMock())

    monkeypatch.setattr(module.AsyncPostgresSaver, "from_conn_string", persistence)
    monkeypatch.setattr(module.AsyncPostgresStore, "from_conn_string", persistence)
    model_refs, vector_refs, load_options = [], [], []

    class CyclicEmbedding(DeterministicHashEmbeddingBackend):
        def __init__(self):
            super().__init__(384)
            self.cycle = self

    def load(*args, **kwargs):
        model = CyclicEmbedding()
        model_refs.append(weakref.ref(model))
        load_options.append(kwargs)
        return model

    monkeypatch.setattr(module.SentenceTransformerEmbeddingBackend, "load", load)
    collection = RecordingCollection()

    def vector_factory(settings, embedding):
        vector = AdvancedChromaVectorStore(collection, embedding, metadata_filter_fallback=True)
        vector_refs.append(weakref.ref(vector))
        return vector

    monkeypatch.setattr(module, "create_advanced_vector_store", vector_factory)
    redis = AsyncMock()
    monkeypatch.setattr(module, "create_redis_client", lambda _: redis)
    parent_store = SimpleNamespace(put_many=AsyncMock())
    monkeypatch.setattr(
        module.RedisParentDocumentStore, "from_redis", lambda *args, **kwargs: parent_store
    )
    monkeypatch.setattr("app.rag.manifest.GENERATED_RAG_ROOT", tmp_path)
    return SimpleNamespace(
        settings=settings,
        corpus=corpus,
        collection=collection,
        reference=reference,
        model_refs=model_refs,
        vector_refs=vector_refs,
        vector_factory=vector_factory,
        load_options=load_options,
        connection=connection,
        parent_store=parent_store,
        redis=redis,
        generated=tmp_path / "advanced-v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_count", [0, 1, 8, 9, 77])
async def test_bounded_missing_children_in_stable_order(harness, missing_count):
    h = harness
    ids = [child.child_id for child in h.corpus.children]
    # Seed a non-prefix subset too: missing IDs must follow corpus order, never set order.
    missing = set(ids[::2] + ids[1::2]) if missing_count == 77 else set(ids[::2][:missing_count])
    h.collection.rows = {
        key: value for key, value in h.reference.rows.items() if key not in missing
    }
    await module.bootstrap(h.settings)
    expected = [child_id for child_id in ids if child_id in missing]
    batches = h.collection.batches
    assert batches == [tuple(expected[i : i + 8]) for i in range(0, len(expected), 8)]
    flat = [child_id for batch in batches for child_id in batch]
    assert len(flat) == len(set(flat)) == missing_count
    assert h.collection.count() == 77
    assert h.collection.rows == h.reference.rows
    assert h.load_options[0]["batch_size"] == 8
    assert h.load_options[0]["local_files_only"] is True
    assert all(ref() is None for ref in h.model_refs + h.vector_refs)


@pytest.mark.asyncio
async def test_partial_failed_index_resumes_only_missing(harness):
    h = harness
    h.collection.fail_batch = 2
    with pytest.raises(ConnectionError):
        await module.bootstrap(h.settings)
    assert h.collection.count() == 8
    h.collection.fail_batch = None
    await module.bootstrap(h.settings)
    assert h.collection.rows == h.reference.rows
    ids = [child_id for batch in h.collection.batches for child_id in batch]
    assert len(ids) == len(set(ids)) == 77


@pytest.mark.asyncio
async def test_bootstrap_model_gone_before_normal_runtime_loads_once(harness, monkeypatch):
    from app.rag import runtime

    h = harness
    await module.bootstrap(h.settings)
    assert len(h.model_refs) == 1 and h.model_refs[0]() is None
    monkeypatch.setattr(runtime, "create_advanced_vector_store", h.vector_factory)
    rag = await runtime.create_advanced_rag_runtime(h.settings, h.redis)
    assert rag.indexed
    assert len(h.model_refs) == 2
    assert h.model_refs[0]() is None and h.model_refs[1]() is not None
    assert "batch_size" not in h.load_options[1]


@pytest.mark.asyncio
async def test_final_count_mismatch_fails_before_redis(harness, capsys):
    harness.collection.wrong_count = True
    with pytest.raises(ValueError, match="collection count"):
        await module.bootstrap(harness.settings)
    harness.parent_store.put_many.assert_not_awaited()
    assert "stage=complete" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_duplicate_corpus_ids_fail_before_writes(harness, monkeypatch):
    duplicate = replace(harness.corpus, children=harness.corpus.children * 2)
    monkeypatch.setattr(module, "build_advanced_corpus", lambda *a, **kw: duplicate)
    with pytest.raises(ValueError, match="duplicate RAG child"):
        await module.bootstrap(harness.settings)
    assert harness.collection.batches == []


@pytest.mark.asyncio
async def test_safe_stages_are_flushed_and_ordered(harness, monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.print", lambda value, **kwargs: calls.append((value, kwargs)))
    await module.bootstrap(harness.settings)
    assert all(options == {"flush": True} for _, options in calls)
    text = "\n".join(value for value, _ in calls)
    assert "unit-only-sensitive-password" not in text and "postgresql://" not in text
    assert all(child.content not in text for child in harness.corpus.children)
    assert text.count("stage=embedding_load_start") == 1
    assert text.count("stage=chroma_index_batch_complete") == 10
    assert text.index("stage=manifest_ready") < text.index("stage=memory_released")
    assert text.index("stage=memory_released") < text.index("stage=complete")
