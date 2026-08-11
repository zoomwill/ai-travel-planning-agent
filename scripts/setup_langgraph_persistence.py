"""Create or migrate LangGraph persistence tables without starting FastAPI."""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import create_strict_serializer


async def setup_persistence() -> bool:
    """Run both official idempotent setup operations and print safe results."""

    settings = Settings()
    connection_uri = settings.langgraph_postgres_uri.get_secret_value()
    saver_ok = False
    store_ok = False

    try:
        async with AsyncPostgresSaver.from_conn_string(
            connection_uri,
            serde=create_strict_serializer(),
        ) as saver:
            await saver.setup()
        saver_ok = True
        print("PASS LangGraph checkpointer: schema is ready")
    except Exception as exc:
        print(f"FAIL LangGraph checkpointer: {type(exc).__name__}")

    try:
        async with AsyncPostgresStore.from_conn_string(connection_uri) as store:
            await store.setup()
        store_ok = True
        print("PASS LangGraph preference store: schema is ready")
    except Exception as exc:
        print(f"FAIL LangGraph preference store: {type(exc).__name__}")

    return saver_ok and store_ok


def main() -> int:
    """Return a nonzero process status when either setup operation fails."""

    return 0 if asyncio.run(setup_persistence()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
