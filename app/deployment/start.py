"""Single-worker container entry point with safe configuration errors and normal SIGTERM."""

import asyncio
import os

import uvicorn

from app.core.config import Settings
from app.deployment.bootstrap import bootstrap
from app.deployment.diagnostics import DeploymentFailure


def port_number(value: str) -> int:
    """Validate Railway's PORT rather than interpolating it into a shell command."""

    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("PORT out of range")
    return port


async def serve() -> None:
    """Bootstrap before traffic, then let Uvicorn manage lifespan and shutdown signals."""

    phase = "settings"
    try:
        settings = Settings()
        port = port_number(os.environ.get("PORT", "8000"))
        phase = "bootstrap"
        await asyncio.wait_for(bootstrap(settings), timeout=600)
        phase = "application"
        from app.main import create_app

        config = uvicorn.Config(
            create_app(settings=settings),
            host="0.0.0.0",
            port=port,
            workers=1,
            access_log=False,
            log_config=None,
            timeout_graceful_shutdown=30,
            proxy_headers=False,
        )
        phase = "uvicorn"
        await uvicorn.Server(config).serve()
    except Exception as error:
        raise DeploymentFailure(phase, error) from None


def main() -> int:
    """Keep invalid settings, credentials and bootstrap exception details out of logs."""

    try:
        asyncio.run(serve())
    except DeploymentFailure as error:
        error.report()
        return 1
    except (Exception, KeyboardInterrupt) as error:
        DeploymentFailure("entrypoint", error).report()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
