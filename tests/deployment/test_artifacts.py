"""Parse checked-in deploy configuration and forbid accidental secret/context inclusion."""

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_railway_and_vercel_configuration():
    railway = tomllib.loads((ROOT / "railway.toml").read_text())
    assert railway["build"]["builder"] == "DOCKERFILE"
    assert railway["deploy"]["healthcheckPath"] == "/ready"
    assert railway["deploy"]["numReplicas"] == 1
    assert "preDeployCommand" not in railway["deploy"]
    vercel = json.loads((ROOT / "frontend/vercel.json").read_text())
    assert vercel["framework"] == "vite" and vercel["outputDirectory"] == "dist"
    assert vercel["installCommand"] == "npm ci"
    assert "env" not in vercel
    assert not any("Content-Security-Policy" == h["key"] for h in vercel["headers"][0]["headers"])


def test_docker_context_and_runtime_contract():
    ignore = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {
        ".env",
        ".env.*",
        ".git",
        ".venv",
        "frontend/node_modules",
        "frontend/dist",
        "**/playwright-report",
        "**/test-results",
        ".pytest_cache",
        ".mypy_cache",
        "coverage",
        "data/generated",
        "models",
    } <= ignore
    docker = (ROOT / "Dockerfile").read_text()
    assert "uv sync --locked --no-dev" in docker
    assert "USER 10001:10001" in docker
    assert "HF_HUB_OFFLINE=1" in docker
    assert (
        "APP_ENV=production AUTH_MODE=auth0 API_DOCS_ENABLED=false METRICS_ENABLED=false" in docker
    )
    assert 'CMD ["python", "-m", "app.deployment.start"]' in docker
    assert "COPY . " not in docker and "ARG " not in docker
    assert "COPY data/knowledge" in docker
    assert len(re.findall(r"@sha256:[0-9a-f]{64}", docker)) == 2


def test_ci_permissions_and_offline_jobs():
    ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    assert ci["permissions"] == {"contents": "read"}
    assert set(ci["on"]) == {"push", "pull_request"}
    assert ci["on"]["push"]["branches"] == ["main"]
    commands = []
    for job in ci["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", step["uses"])
            commands.append(step.get("run", ""))
    assert "uv sync --locked" in commands
    assert "uv run pytest -q" in commands
    assert "npm ci" in commands and "npm run test:e2e" in commands
    assert not any("RUN_LLM" in c or "RUN_DUFFEL" in c or "RUN_LITEAPI" in c for c in commands)
    assert ci["env"]["AUTH_MODE"] == "demo"
