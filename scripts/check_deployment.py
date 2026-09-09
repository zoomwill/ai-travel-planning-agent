"""Explicit local container acceptance; no Auth0, Qwen or travel-provider requests."""

import argparse
import json
import os
import subprocess
import time
from collections.abc import Callable
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.deployment.diagnostics import BOOTSTRAP_STAGES

IMAGE = "travel-planner:p18"
NETWORK = "ai_travel_planner_codex_pack_default"
CHROMA_IMAGE = "chromadb/chroma:1.5.9"

# This probe runs in the already-built Python image on Docker's private test network.
# It neither loads a model nor needs host-published Chroma ports.
CHROMA_PROBE = """
import json, sys, time, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
url = 'http://' + sys.argv[1] + ':8000/api/v2/healthcheck'
for _ in range(30):
    try:
        with opener.open(url, timeout=1) as response:
            data = json.load(response)
        if data.get('is_executor_ready') and data.get('is_log_client_ready'):
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(1)
raise SystemExit(1)
"""


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


def wait_ready(client: httpx.Client, *, alive: Callable[[], bool] | None = None) -> None:
    """Wait a bounded time for bootstrap and application lifespan, not external searches."""

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if alive is not None and not alive():
            raise RuntimeError("container exited before readiness")
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


def fresh_batch_counts(logs: str) -> list[int]:
    """Validate exact generated batch lines, without forwarding any arbitrary container output."""

    lines = logs.splitlines()
    expected = [8] * 9 + [5]
    for stage in ("chroma_index_batch_start", "chroma_index_batch_complete"):
        actual = [line for line in lines if line.startswith(f"BOOTSTRAP stage={stage} ")]
        required = [
            f"BOOTSTRAP stage={stage} batch={i} batches=10 children={size}"
            for i, size in enumerate(expected, start=1)
        ]
        if actual != required:
            raise RuntimeError("fresh index batches differ")
    for marker in (
        "BOOTSTRAP stage=chroma_existing_ids_ready children=77 batches=10",
        "BOOTSTRAP stage=chroma_ready children=77",
        "BOOTSTRAP stage=memory_released",
        "BOOTSTRAP stage=complete",
    ):
        if lines.count(marker) != 1:
            raise RuntimeError("fresh bootstrap completion differs")
    if lines.index("BOOTSTRAP stage=memory_released") > lines.index("BOOTSTRAP stage=complete"):
        raise RuntimeError("model release ordering differs")
    return expected


def memory_peak(name: str) -> int | None:
    """Read the kernel cgroup v2 high-water mark, or explicitly return unavailable."""

    try:
        value = docker(
            "exec",
            name,
            "python",
            "-c",
            "from pathlib import Path; print(int(Path('/sys/fs/cgroup/memory.peak').read_text()))",
        )
        peak = int(value)
        return peak if peak > 0 else None
    except Exception:
        return None


def main(*, fresh_index: bool = False, memory_mib: int = 1024) -> int:
    """Exercise an ephemeral API container on the existing private Compose network."""

    name = "p18-api-check-" + uuid4().hex
    created = False
    chroma_created = False
    chroma_name = "p18-bootstrap-chroma-" + uuid4().hex
    result_code = 1
    stage = "configuration"
    try:
        if memory_mib not in (1024, 2048):
            raise ValueError("unsupported local acceptance memory cap")
        settings = Settings()
        stage = "image inspection"
        info = json.loads(docker("image", "inspect", IMAGE))[0]
        if fresh_index:
            stage = "isolated Chroma creation"
            docker(
                "run",
                "-d",
                "--name",
                chroma_name,
                "--network",
                NETWORK,
                "--tmpfs",
                "/data:rw,size=256m,mode=1777",
                CHROMA_IMAGE,
            )
            chroma_created = True
            stage = "isolated Chroma readiness"
            docker(
                "run",
                "--rm",
                "--network",
                NETWORK,
                "--entrypoint",
                "python",
                IMAGE,
                "-c",
                CHROMA_PROBE,
                chroma_name,
            )
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
            "CHROMA_HOST": chroma_name if fresh_index else "chroma",
            "CHROMA_PORT": "8000",
        }
        environment.update(variables)
        arguments = ["run", "-d", "--name", name, "--network", NETWORK, "-p", "127.0.0.1::8080"]
        if fresh_index:
            variables["RAG_BOOTSTRAP_BATCH_SIZE"] = "8"
            environment.update(variables)
            arguments.extend(["--memory", f"{memory_mib}m", "--memory-swap", f"{memory_mib}m"])
        for key in variables:
            arguments.extend(["--env", key])  # Values never appear in argv, logs or files.
        stage = "container creation"
        docker(*arguments, IMAGE, environment=environment)
        created = True

        def alive() -> bool:
            """Fail promptly if bootstrap was killed instead of waiting out the HTTP deadline."""

            return bool(
                json.loads(docker("inspect", "--format", "{{json .State}}", name))["Running"]
            )

        port = published_port(name)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            stage = "initial readiness"
            wait_ready(client, alive=alive)
            stage = "health and RAG"
            if client.get("/health").status_code != 200:
                raise RuntimeError("health failed")
            rag = client.get("/api/v1/rag/status")
            if rag.status_code != 200 or not rag.json().get("indexed"):
                raise RuntimeError("RAG unavailable")
            before = rag.json()
            if fresh_index:
                if before.get("child_count") != 77:
                    raise RuntimeError("fresh child count differs")
                counts = fresh_batch_counts(docker("logs", name))
                print(
                    f"PASS fresh index: 77 children, {len(counts)} batches (9 x 8 + 5)", flush=True
                )
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
            # Several successful probes prove the service remains alive after initial readiness.
            for _ in range(5):
                time.sleep(1)
                if client.get("/ready").status_code != 200:
                    raise RuntimeError("readiness did not remain stable")
        first_peak = memory_peak(name) if fresh_index else None
        stage = "container restart"
        docker("restart", "--time", "40", name)
        port = published_port(name)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            stage = "restart readiness"
            wait_ready(client, alive=alive)
            stage = "restart RAG comparison"
            after = client.get("/api/v1/rag/status").json()
            if before != after:
                raise RuntimeError("RAG status changed across restart")
            print("PASS container restart: same RAG status; idempotent bootstrap")
        if fresh_index:
            logs = docker("logs", name)
            if logs.count("BOOTSTRAP stage=chroma_index_batch_start ") != 10:
                raise RuntimeError("restart unexpectedly reindexed children")
            peaks = [value for value in (first_peak, memory_peak(name)) if value is not None]
            if peaks:
                print(f"INFO observed cgroup memory.peak bytes: {max(peaks)}", flush=True)
            else:
                print("INFO cgroup memory peak: NOT AVAILABLE", flush=True)
            print(
                f"INFO local image architecture: {info['Architecture']}; "
                f"API limit={memory_mib * 1024 * 1024} bytes"
            )
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
        if created:
            try:
                state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
                print(
                    f"INFO container OOMKilled={bool(state['OOMKilled'])} "
                    f"exit_code={int(state['ExitCode'])}"
                )
                stages = [
                    line.split()[1].removeprefix("stage=")
                    for line in docker("logs", name).splitlines()
                    if line.startswith("BOOTSTRAP stage=")
                ]
                if stages and stages[-1] in BOOTSTRAP_STAGES:
                    print(f"INFO last bootstrap stage={stages[-1]}")
            except Exception:
                pass
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
        if chroma_created:
            try:
                docker("stop", "--time", "20", chroma_name)
                docker("rm", chroma_name)
                print(
                    "PASS cleanup: isolated Chroma container/tmpfs removed; existing data untouched"
                )
            except Exception:
                print("FAIL isolated Chroma cleanup; manual Docker inspection required")
                result_code = 1
    return result_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh-index", action="store_true", help="Use isolated empty Chroma and a 1 GiB API limit"
    )
    parser.add_argument(
        "--memory-mib",
        type=int,
        choices=(1024, 2048),
        default=1024,
        help="Local fresh-index API cap only; never changes Railway",
    )
    args = parser.parse_args()
    raise SystemExit(main(fresh_index=args.fresh_index, memory_mib=args.memory_mib))
