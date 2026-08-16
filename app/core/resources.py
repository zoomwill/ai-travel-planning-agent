"""Create and clean up the application's infrastructure resources."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.infrastructure.chroma import ChromaClientProvider
from app.infrastructure.postgres import create_postgres_engine
from app.infrastructure.redis import create_redis_client
from app.mcp_tools.backend import UnavailableMCPTravelSearchBackend
from app.mcp_tools.client import MCPRuntime, create_mcp_runtime
from app.rag.runtime import AdvancedRagRuntime, create_advanced_rag_runtime
from app.search.backend import SearchBackend


@dataclass(slots=True)
class AppResources:
    """Resources owned by one running FastAPI application."""

    settings: Settings
    postgres_engine: AsyncEngine
    redis_client: Redis
    chroma_client: ChromaClientProvider
    rag_runtime: AdvancedRagRuntime | None = None
    mcp_runtime: MCPRuntime | None = None
    search_backend: SearchBackend | None = None


ResourceFactory = Callable[[Settings], Awaitable[AppResources]]


async def create_app_resources(settings: Settings) -> AppResources:
    """Create lazy clients and clean up anything made before a startup failure."""

    postgres_engine: AsyncEngine | None = None
    redis_client: Redis | None = None
    chroma_client: ChromaClientProvider | None = None

    try:
        postgres_engine = create_postgres_engine(settings)
        redis_client = create_redis_client(settings)
        chroma_client = ChromaClientProvider(settings)
        rag_runtime = await create_advanced_rag_runtime(settings, redis_client)
        mcp_runtime: MCPRuntime | None = None
        search_backend: SearchBackend | None = None
        if settings.travel_search_backend_mode == "mcp":
            try:
                mcp_runtime = await create_mcp_runtime(settings)
                search_backend = mcp_runtime.backend
            except Exception:
                search_backend = UnavailableMCPTravelSearchBackend()
        return AppResources(
            settings=settings,
            postgres_engine=postgres_engine,
            redis_client=redis_client,
            chroma_client=chroma_client,
            rag_runtime=rag_runtime,
            mcp_runtime=mcp_runtime,
            search_backend=search_backend,
        )
    except BaseException:
        if chroma_client is not None:
            with suppress(Exception):
                await chroma_client.aclose()
        if redis_client is not None:
            with suppress(Exception):
                await redis_client.aclose()
        if postgres_engine is not None:
            with suppress(Exception):
                await postgres_engine.dispose()
        raise


async def close_app_resources(resources: AppResources) -> None:
    """Attempt every cleanup and report failures together after all have run."""

    errors: list[Exception] = []

    cleanups: tuple[Callable[[], Awaitable[None]], ...] = (
        resources.chroma_client.aclose,
        resources.redis_client.aclose,
        resources.postgres_engine.dispose,
    )
    for cleanup in cleanups:
        try:
            await cleanup()
        except Exception as exc:
            errors.append(exc)

    if errors:
        raise ExceptionGroup("infrastructure resource cleanup failed", errors)
