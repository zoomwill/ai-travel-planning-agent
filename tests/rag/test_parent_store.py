"""Offline tests for Redis-first parent lookup and local fallback."""

import asyncio

from app.rag.parent_store import LocalManifestParentStore, RedisParentDocumentStore
from tests.rag.helpers import make_parent


class FakeRedisParentClient:
    """A tiny string store that can simulate Redis failure."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail = False

    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("private redis detail")
        return self.values.get(name)

    async def set(self, name: str, value: str, **kwargs: object) -> bool:
        del kwargs
        if self.fail:
            raise ConnectionError("private redis detail")
        self.values[name] = value
        return True


async def test_redis_parent_hit_and_local_fallback() -> None:
    """Redis wins when available and local manifest survives a connection failure."""

    parent = make_parent("a")
    local = LocalManifestParentStore([parent])
    redis = FakeRedisParentClient()
    store = RedisParentDocumentStore(redis, pipeline_version="advanced-v1", fallback=local)
    await store.put_many([parent])

    assert await store.get(parent.parent_id) == parent
    redis.fail = True
    assert await store.get(parent.parent_id) == parent
    assert await store.get("z" * 64) is None


async def test_parent_timeout_opens_local_fallback_for_remaining_reads() -> None:
    """Only the first unresponsive Redis read waits; later parents go straight local."""

    class HangingRedis(FakeRedisParentClient):
        def __init__(self) -> None:
            super().__init__()
            self.get_calls = 0

        async def get(self, name: str) -> str | None:
            del name
            self.get_calls += 1
            await asyncio.sleep(10)
            return None

    first = make_parent("a")
    second = make_parent("b")
    redis = HangingRedis()
    store = RedisParentDocumentStore(
        redis,
        pipeline_version="advanced-v1",
        fallback=LocalManifestParentStore([first, second]),
        operation_timeout_seconds=0.01,
    )

    assert await store.get(first.parent_id) == first
    assert await store.get(second.parent_id) == second
    assert redis.get_calls == 1
