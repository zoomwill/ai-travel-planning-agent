"""Pure cache-aside tests for canonical keys, TTL, corruption, and failure."""

import asyncio

from app.core.config import Settings
from app.rag.cache import RedisRetrievalCache, build_retrieval_cache_key
from app.rag.models import AdvancedRetrievalResult, QueryBundle, RetrievalDiagnostics


class FakeCacheClient:
    """Record exact Redis commands without a Docker service."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.fail = False

    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("private redis detail")
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        if self.fail:
            raise ConnectionError("private redis detail")
        self.values[name] = value
        self.set_calls.append((name, ex))
        return True

    async def delete(self, *names: str) -> int:
        self.deleted.extend(names)
        for name in names:
            self.values.pop(name, None)
        return len(names)


def result() -> AdvancedRetrievalResult:
    """Build a cacheable parent-level result with no embeddings."""

    return AdvancedRetrievalResult(
        contexts=["Tokyo parent context"],
        parent_ids=["p" * 64],
        diagnostics=RetrievalDiagnostics(
            pipeline_version="advanced-v1",
            corpus_fingerprint="f" * 64,
            embedding_backend="sentence_transformers",
            embedding_model="demo-model",
            query_variant_count=2,
            dense_candidate_count=2,
            sparse_candidate_count=1,
            fused_candidate_count=2,
            reranked_candidate_count=1,
            returned_parent_count=1,
            metadata_filter_applied=True,
            metadata_filter_fallback_used=False,
            cache_status="miss",
        ),
    )


async def test_cache_miss_set_with_ttl_then_hit() -> None:
    """SET receives EX and a hit never contains an embedding field."""

    client = FakeCacheClient()
    cache = RedisRetrievalCache(client, ttl_seconds=123)

    assert (await cache.get("key")).status == "miss"
    assert await cache.set("key", result()) is True
    lookup = await cache.get("key")

    assert client.set_calls == [("key", 123)]
    assert lookup.status == "hit"
    assert lookup.result is not None
    assert lookup.result.diagnostics.cache_status == "hit"
    assert '"embeddings"' not in client.values["key"].casefold()


async def test_corrupt_key_is_deleted_alone_and_unavailable_is_safe() -> None:
    """Corrupt JSON removes only its key while a connection error returns unavailable."""

    client = FakeCacheClient()
    client.values = {"bad": "{", "other": result().model_dump_json()}
    cache = RedisRetrievalCache(client, ttl_seconds=60)

    assert (await cache.get("bad")).status == "corrupt"
    assert client.deleted == ["bad"]
    assert "other" in client.values
    client.fail = True
    assert (await cache.get("missing")).status == "unavailable"
    assert await cache.set("missing", result()) is False


async def test_cache_operation_timeout_degrades_to_unavailable() -> None:
    """An unresponsive Redis call cannot block the retrieval pipeline indefinitely."""

    class HangingCacheClient(FakeCacheClient):
        async def get(self, name: str) -> str | None:
            del name
            await asyncio.sleep(10)
            return None

    cache = RedisRetrievalCache(
        HangingCacheClient(),
        ttl_seconds=60,
        operation_timeout_seconds=0.01,
    )

    assert (await cache.get("key")).status == "unavailable"


def test_cache_key_is_canonical_and_changes_with_corpus_or_config() -> None:
    """A new corpus or retrieval-affecting setting naturally creates a new key."""

    settings = Settings(_env_file=None)
    bundle = QueryBundle(
        original_query="Tokyo photography",
        query_variants=["Tokyo photography", "Tokyo street photography"],
        destination="Tokyo",
        metadata_filter={"city": "Tokyo"},
    )
    first = build_retrieval_cache_key(
        settings=settings,
        corpus_fingerprint="a" * 64,
        query_bundle=bundle,
    )
    repeated = build_retrieval_cache_key(
        settings=settings,
        corpus_fingerprint="a" * 64,
        query_bundle=bundle,
    )
    changed_corpus = build_retrieval_cache_key(
        settings=settings,
        corpus_fingerprint="b" * 64,
        query_bundle=bundle,
    )
    changed_config = build_retrieval_cache_key(
        settings=settings.model_copy(update={"rag_rrf_k": 61}),
        corpus_fingerprint="a" * 64,
        query_bundle=bundle,
    )

    assert first == repeated
    assert first.startswith("rag:cache:advanced-v1:")
    assert first != changed_corpus
    assert first != changed_config
