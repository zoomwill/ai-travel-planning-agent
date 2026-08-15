"""Canonical Redis cache-aside for final P10 parent-level results."""

import asyncio
from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis

from app.core.config import Settings
from app.rag.identity import canonical_sha256
from app.rag.models import AdvancedRetrievalResult, CacheStatus, QueryBundle


class AsyncCacheClient(Protocol):
    """Narrow async Redis surface used by the cache adapter."""

    async def get(self, name: str) -> str | bytes | None:
        """Read one cache key."""

    async def set(self, name: str, value: str, *, ex: int) -> object:
        """Write one expiring cache value."""

    async def delete(self, *names: str) -> int:
        """Delete only supplied corrupt keys."""


@dataclass(frozen=True, slots=True)
class CacheLookup:
    """One cache read result plus its safe public status."""

    result: AdvancedRetrievalResult | None
    status: CacheStatus


class RedisRetrievalCache:
    """Store final JSON results with TTL and recover safely from corruption."""

    def __init__(
        self,
        redis_client: AsyncCacheClient,
        *,
        ttl_seconds: int,
        operation_timeout_seconds: float = 2.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be greater than zero")
        if operation_timeout_seconds <= 0:
            raise ValueError("cache operation timeout must be greater than zero")
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._operation_timeout_seconds = operation_timeout_seconds

    @classmethod
    def from_redis(
        cls,
        redis_client: Redis,
        *,
        ttl_seconds: int,
        operation_timeout_seconds: float = 2.0,
    ) -> "RedisRetrievalCache":
        """Adapt the installed redis-py client to the cache protocol."""

        return cls(
            cast(AsyncCacheClient, redis_client),
            ttl_seconds=ttl_seconds,
            operation_timeout_seconds=operation_timeout_seconds,
        )

    @property
    def ttl_seconds(self) -> int:
        """Return the configured positive TTL."""

        return self._ttl_seconds

    async def get(self, key: str) -> CacheLookup:
        """Return hit/miss/corrupt/unavailable without exposing Redis errors."""

        try:
            raw = await asyncio.wait_for(
                self._redis.get(key),
                timeout=self._operation_timeout_seconds,
            )
        except Exception:
            return CacheLookup(None, "unavailable")
        if raw is None:
            return CacheLookup(None, "miss")
        try:
            result = AdvancedRetrievalResult.model_validate_json(raw)
        except Exception:
            try:
                await asyncio.wait_for(
                    self._redis.delete(key),
                    timeout=self._operation_timeout_seconds,
                )
            except Exception:
                pass
            return CacheLookup(None, "corrupt")
        diagnostics = result.diagnostics.model_copy(update={"cache_status": "hit"})
        return CacheLookup(result.model_copy(update={"diagnostics": diagnostics}), "hit")

    async def set(self, key: str, result: AdvancedRetrievalResult) -> bool:
        """Write one JSON value with Redis SET EX; failure keeps retrieval usable."""

        try:
            await asyncio.wait_for(
                self._redis.set(key, result.model_dump_json(), ex=self._ttl_seconds),
                timeout=self._operation_timeout_seconds,
            )
        except Exception:
            return False
        return True


def build_retrieval_cache_key(
    *,
    settings: Settings,
    corpus_fingerprint: str,
    query_bundle: QueryBundle,
) -> str:
    """Hash every retrieval-affecting value into a non-secret canonical key."""

    digest = canonical_sha256(
        {
            "corpus_fingerprint": corpus_fingerprint,
            "dense_top_k": settings.rag_dense_top_k,
            "embedding_backend": settings.rag_embedding_backend,
            "embedding_model": settings.rag_embedding_model,
            "final_parent_k": settings.rag_final_parent_k,
            "fusion_top_k": settings.rag_fusion_top_k,
            "metadata_filter": query_bundle.metadata_filter,
            "pipeline_version": settings.rag_pipeline_version,
            "query_variants": query_bundle.query_variants,
            "rerank_top_k": settings.rag_rerank_top_k,
            "rrf_k": settings.rag_rrf_k,
            "sparse_top_k": settings.rag_sparse_top_k,
        }
    )
    return f"rag:cache:{settings.rag_pipeline_version}:{digest}"
