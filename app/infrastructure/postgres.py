"""Asynchronous PostgreSQL engine creation and readiness checks."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.core.exceptions import InfrastructureError, InfrastructureService


def create_postgres_engine(settings: Settings) -> AsyncEngine:
    """Create a lazy SQLAlchemy async engine with stale-connection detection."""

    return create_async_engine(settings.postgres_url, pool_pre_ping=True)


async def check_postgres(engine: AsyncEngine) -> None:
    """Run a minimal query to prove PostgreSQL can accept application traffic."""

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            if result.scalar_one() != 1:
                raise InfrastructureError(InfrastructureService.POSTGRESQL)
    except InfrastructureError:
        raise
    except Exception as exc:
        raise InfrastructureError(InfrastructureService.POSTGRESQL) from exc
