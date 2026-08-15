"""Redis parent documents with an in-memory local manifest fallback."""

import asyncio
from typing import Protocol, cast

from redis.asyncio import Redis

from app.rag.models import ParentDocument


class ParentDocumentStore(Protocol):
    """Small async parent store contract used by indexing and retrieval."""

    async def get(self, parent_id: str) -> ParentDocument | None:
        """Return one parent or None."""

    async def put_many(self, parents: list[ParentDocument]) -> None:
        """Store or update parents by deterministic ID."""


class AsyncKeyValueStore(Protocol):
    """Redis methods used without coupling tests to a live client."""

    async def get(self, name: str) -> str | bytes | None:
        """Read one string key."""

    async def set(self, name: str, value: str, **kwargs: object) -> object:
        """Write one string key."""


class LocalManifestParentStore:
    """Read parents from validated local manifest data without external I/O."""

    def __init__(self, parents: list[ParentDocument]) -> None:
        self._parents = {parent.parent_id: parent for parent in parents}

    @property
    def parent_count(self) -> int:
        """Return the number of unique local parents."""

        return len(self._parents)

    async def get(self, parent_id: str) -> ParentDocument | None:
        """Return one local parent by exact ID."""

        return self._parents.get(parent_id)

    async def put_many(self, parents: list[ParentDocument]) -> None:
        """Update this in-memory store for unit tests and explicit indexing."""

        self._parents.update({parent.parent_id: parent for parent in parents})


class RedisParentDocumentStore:
    """Use Redis first and fall back to the local manifest on misses or errors."""

    def __init__(
        self,
        redis_client: AsyncKeyValueStore,
        *,
        pipeline_version: str,
        fallback: ParentDocumentStore,
        operation_timeout_seconds: float = 2.0,
    ) -> None:
        if operation_timeout_seconds <= 0:
            raise ValueError("parent store operation timeout must be greater than zero")
        self._redis = redis_client
        self._prefix = f"rag:parent:{pipeline_version}:"
        self._fallback = fallback
        self._operation_timeout_seconds = operation_timeout_seconds
        self._redis_available = True

    @classmethod
    def from_redis(
        cls,
        redis_client: Redis,
        *,
        pipeline_version: str,
        fallback: ParentDocumentStore,
        operation_timeout_seconds: float = 2.0,
    ) -> "RedisParentDocumentStore":
        """Adapt the installed redis-py async client to the narrow protocol."""

        return cls(
            cast(AsyncKeyValueStore, redis_client),
            pipeline_version=pipeline_version,
            fallback=fallback,
            operation_timeout_seconds=operation_timeout_seconds,
        )

    def key_for(self, parent_id: str) -> str:
        """Return one namespaced deterministic parent key."""

        return f"{self._prefix}{parent_id}"

    async def get(self, parent_id: str) -> ParentDocument | None:
        """Validate Redis JSON or use the local manifest fallback."""

        if self._redis_available:
            try:
                raw = await asyncio.wait_for(
                    self._redis.get(self.key_for(parent_id)),
                    timeout=self._operation_timeout_seconds,
                )
                if raw is not None:
                    return ParentDocument.model_validate_json(raw)
            except Exception:
                self._redis_available = False
        return await self._fallback.get(parent_id)

    async def put_many(self, parents: list[ParentDocument]) -> None:
        """Upsert only exact P10 parent keys without scanning or flushing Redis."""

        for parent in parents:
            await asyncio.wait_for(
                self._redis.set(
                    self.key_for(parent.parent_id),
                    parent.model_dump_json(),
                ),
                timeout=self._operation_timeout_seconds,
            )
