"""Unit tests for lazy Chroma client construction."""

import asyncio

import pytest

from app.core.config import Settings
from app.core.exceptions import InfrastructureError
from app.infrastructure.chroma import ChromaClientProvider


class FakeAsyncChromaClient:
    """Return a deterministic heartbeat without Docker."""

    def __init__(self, heartbeat: int = 1) -> None:
        self.value = heartbeat

    async def heartbeat(self) -> int:
        """Return the configured heartbeat."""

        return self.value


@pytest.mark.asyncio
async def test_provider_is_lazy_and_caches_one_client() -> None:
    calls = 0
    client = FakeAsyncChromaClient()

    async def factory(*, host: str, port: int, ssl: bool) -> FakeAsyncChromaClient:
        nonlocal calls
        calls += 1
        assert (host, port, ssl) == ("127.0.0.1", 8001, False)
        return client

    provider = ChromaClientProvider(Settings(_env_file=None), factory)
    assert calls == 0

    assert await provider.get_client() is client
    assert await provider.get_client() is client
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_access_creates_only_one_client() -> None:
    calls = 0

    async def factory(*, host: str, port: int, ssl: bool) -> FakeAsyncChromaClient:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return FakeAsyncChromaClient()

    provider = ChromaClientProvider(Settings(_env_file=None), factory)
    first, second = await asyncio.gather(provider.get_client(), provider.get_client())

    assert first is second
    assert calls == 1


@pytest.mark.asyncio
async def test_failed_creation_is_wrapped_and_can_retry() -> None:
    calls = 0

    async def factory(*, host: str, port: int, ssl: bool) -> FakeAsyncChromaClient:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("private endpoint detail")
        return FakeAsyncChromaClient()

    provider = ChromaClientProvider(Settings(_env_file=None), factory)

    with pytest.raises(InfrastructureError):
        await provider.heartbeat()
    await provider.heartbeat()

    assert calls == 2


@pytest.mark.asyncio
async def test_aclose_releases_cached_reference() -> None:
    calls = 0

    async def factory(*, host: str, port: int, ssl: bool) -> FakeAsyncChromaClient:
        nonlocal calls
        calls += 1
        return FakeAsyncChromaClient()

    provider = ChromaClientProvider(Settings(_env_file=None), factory)
    await provider.get_client()
    await provider.aclose()
    await provider.get_client()

    assert calls == 2
