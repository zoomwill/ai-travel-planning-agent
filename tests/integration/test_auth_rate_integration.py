"""Explicit Redis Lua concurrency/expiry acceptance; never contacts Auth0 or suppliers."""

import asyncio
import os
from uuid import uuid4

import pytest

from app.auth.rate_limit import ADMIT_SCRIPT
from app.core.config import Settings
from app.infrastructure.redis import create_redis_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1", reason="explicit Docker gate required"
    ),
]


@pytest.mark.asyncio
async def test_redis_atomic_limits_and_expiry():
    client = create_redis_client(Settings())
    prefix = "p18-test:" + uuid4().hex
    keys = [prefix + ":user-a", prefix + ":global", prefix + ":user-b"]
    try:
        results = await asyncio.gather(
            *[client.eval(ADMIT_SCRIPT, 2, keys[0], keys[1], 3, 60, 4, 60) for _ in range(12)]
        )
        assert results.count(0) == 3
        assert results.count(60) == 9
        assert await client.get(keys[0]) == "3"
        assert 0 < await client.ttl(keys[0]) <= 60
        assert await client.eval(ADMIT_SCRIPT, 2, keys[2], keys[1], 3, 60, 4, 60) == 0
        assert await client.eval(ADMIT_SCRIPT, 2, keys[2], keys[1], 3, 60, 4, 60) == 60
        assert await client.get(keys[2]) == "1"  # Denied requests do not partially consume buckets.
        await client.expire(keys[0], 0)
        assert await client.get(keys[0]) is None
    finally:
        await client.delete(
            *keys
        )  # Only this fresh UUID's test keys, never user quota or RAG keys.
        await client.aclose()
