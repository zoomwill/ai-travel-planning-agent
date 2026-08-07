"""Asynchronous Redis client creation and readiness checks."""

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import InfrastructureError, InfrastructureService


def create_redis_client(settings: Settings) -> Redis:
    """Create a lazy Redis client configured with finite socket timeouts."""

    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
        socket_connect_timeout=settings.infrastructure_timeout_seconds,
        socket_timeout=settings.infrastructure_timeout_seconds,
    )


async def check_redis(client: Redis) -> None:
    """Send Redis PING and require its boolean success response."""

    try:
        if await client.ping() is not True:
            raise InfrastructureError(InfrastructureService.REDIS)
    except InfrastructureError:
        raise
    except Exception as exc:
        raise InfrastructureError(InfrastructureService.REDIS) from exc
