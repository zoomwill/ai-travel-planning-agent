"""Explicit local container acceptance; no Auth0, Qwen or travel-provider requests."""

import json
import os
import subprocess
import time
from uuid import uuid4

import httpx

from app.core.config import Settings

IMAGE = "travel-planner:p18"
NETWORK = "ai_travel_planner_codex_pack_default"


def docker(*arguments: str, environment: dict[str, str] | None = None) -> str:
    """Capture Docker output internally; never forward config or arbitrary daemon errors."""

    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=True,
    )
    return (result.stdout + (result.stderr if arguments[0] == "logs" else "")).strip()


def wait_ready(client: httpx.Client) -> None:
    """Wait a bounded time for bootstrap and application lifespan, not external searches."""

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if client.get("/ready", timeout=10).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError("container readiness deadline")


def published_port(name: str) -> int:
    """Read the current ephemeral host port, including after Docker reconnects networking."""

    bindings = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
    return int(bindings["8080/tcp"][0]["HostPort"])


def main() -> int:
    """Exercise an ephemeral API container on the existing private Compose network."""

    name = "p18-api-check-" + uuid4().hex
    created = False
    result_code = 1
    stage = "configuration"
    try:
        settings = Settings()
        stage = "image inspection"
        info = json.loads(docker("image", "inspect", IMAGE))[0]
        environment = os.environ.copy()
        variables = {
            "APP_ENV": "development",
            "AUTH_MODE": "demo",
            "PORT": "8080",
            "AGENT_REASONING_MODE": "deterministic",
            "TRAVEL_DATA_MODE": "demo",
            "TRAVEL_SEARCH_BACKEND_MODE": "direct",
            "POSTGRES_HOST": "postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": settings.postgres_db,
            "POSTGRES_USER": settings.postgres_user,
            "POSTGRES_PASSWORD": settings.postgres_password.get_secret_value(),
            "REDIS_HOST": "redis",
            "REDIS_PORT": "6379",
            "CHROMA_HOST": "chroma",
            "CHROMA_PORT": "8000",
        }
        environment.update(variables)
        arguments = ["run", "-d", "--name", name, "--network", NETWORK, "-p", "127.0.0.1::8080"]
        for key in variables:
            arguments.extend(["--env", key])  # Values never appear in argv, logs or files.
        stage = "container creation"
        docker(*arguments, IMAGE, environment=environment)
        created = True
        port = published_port(name)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            stage = "initial readiness"
            wait_ready(client)
            stage = "health and RAG"
            if client.get("/health").status_code != 200:
                raise RuntimeError("health failed")
            rag = client.get("/api/v1/rag/status")
            if rag.status_code != 200 or not rag.json().get("indexed"):
                raise RuntimeError("RAG unavailable")
            before = rag.json()
            stage = "deterministic planning"
            response = client.post(
                "/api/v1/agents/plans",
                json={
                    "origin": "Shanghai",
                    "destination": "Tokyo",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-14",
                    "budget": "10000",
                    "currency": "CNY",
                    "travelers": 1,
                    "preferences": ["photography"],
                },
            )
            if response.status_code != 200:
                raise RuntimeError("demo planning failed")
            print(
                "PASS container: health, readiness, prepared RAG and deterministic Agent plan",
                flush=True,
            )
        stage = "container restart"
        docker("restart", "--time", "40", name)
        port = published_port(name)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            stage = "restart readiness"
            wait_ready(client)
            stage = "restart RAG comparison"
            after = client.get("/api/v1/rag/status").json()
            if before != after:
                raise RuntimeError("RAG status changed across restart")
            print("PASS container restart: same RAG status; idempotent bootstrap")
        stage = "image environment"
        image_environment = info["Config"].get("Env", [])
        prohibited = (
            "QWEN_API_KEY=",
            "DUFFEL_ACCESS_TOKEN=",
            "LITEAPI_API_KEY=",
            "POSTGRES_PASSWORD=",
            "REDIS_PASSWORD=",
            "AUTH0_CLIENT_SECRET=",
        )
        if any(value.startswith(prohibited) for value in image_environment):
            raise RuntimeError("unexpected image credential variable")
        stage = "graceful shutdown"
        docker("stop", "--time", "40", name)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
        logs = docker("logs", name)
        if (
            state["Running"]
            or state["ExitCode"] not in (0, 143)
            or "Application resources stopped." not in logs
        ):
            raise RuntimeError("graceful shutdown unverified")
        print("PASS container shutdown: application resources closed after SIGTERM")
        print(f"INFO image size bytes: {info['Size']}")
        print(f"INFO image runtime user: {info['Config']['User']}")
        print("PASS image environment: no backend credential variables")
        result_code = 0
    except Exception:
        print(f"FAIL local container at {stage}; check Docker, image and private dependencies")
        result_code = 1
    finally:
        if created:
            try:
                docker("stop", "--time", "40", name)
                docker("rm", name)  # Only this test's own container; never -v or volume removal.
                print("PASS cleanup: temporary API container removed; named volumes retained")
            except Exception:
                print("FAIL temporary container cleanup; manual Docker inspection required")
                result_code = 1
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
