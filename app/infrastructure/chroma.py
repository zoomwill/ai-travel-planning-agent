"""Lazy asynchronous Chroma HTTP client and readiness checks."""

import asyncio
from collections.abc import Awaitable
from typing import Protocol

import chromadb

from app.core.config import Settings
from app.core.exceptions import InfrastructureError, InfrastructureService


class AsyncChromaClient(Protocol):
    """Small public client surface needed by Phase P02."""

    async def heartbeat(self) -> int:
        """Return Chroma's nanosecond heartbeat value."""


class ChromaClientFactory(Protocol):
    """Callable shape used to inject the official client in tests."""

    def __call__(
        self,
        *,
        host: str,
        port: int,
        ssl: bool,
    ) -> Awaitable[AsyncChromaClient]:
        """Create an asynchronous Chroma client."""


async def create_chroma_http_client(
    *,
    host: str,
    port: int,
    ssl: bool,
) -> AsyncChromaClient:
    """Create Chroma's official asynchronous HTTP client."""

    return await chromadb.AsyncHttpClient(host=host, port=port, ssl=ssl)


class ChromaClientProvider:
    """Create Chroma lazily because its async factory performs network requests."""

    def __init__(
        self,
        settings: Settings,
        client_factory: ChromaClientFactory = create_chroma_http_client,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._client: AsyncChromaClient | None = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> AsyncChromaClient:
        """Return the cached client, creating it once when first needed."""

        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await self._client_factory(
                        host=self._settings.chroma_host,
                        port=self._settings.chroma_port,
                        ssl=self._settings.chroma_ssl,
                    )
        return self._client

    async def heartbeat(self) -> None:
        """Call Chroma's official API v2 heartbeat through its async client."""

        try:
            heartbeat = await (await self.get_client()).heartbeat()
            if heartbeat < 0:
                raise InfrastructureError(InfrastructureService.CHROMA)
        except InfrastructureError:
            raise
        except Exception as exc:
            raise InfrastructureError(InfrastructureService.CHROMA) from exc

    async def aclose(self) -> None:
        """Release this provider's reference to the Chroma client.

        Chroma 1.5.9 does not expose a public async close method on AsyncClientAPI.
        The application deliberately avoids reaching into private client internals.
        """

        async with self._lock:
            self._client = None
