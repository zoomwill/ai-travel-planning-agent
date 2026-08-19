"""Check the local P13 API, Prometheus target, and provisioned Grafana objects."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

_METRIC_NAMES = (
    "travel_planner_http_requests_total",
    "travel_planner_graph_runs_total",
    "travel_planner_graph_node_duration_seconds",
    "travel_planner_rag_searches_total",
    "travel_planner_search_tasks_total",
    "travel_planner_sse_connections_total",
    "travel_planner_dependency_ready",
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One beginner-readable check result without credentials."""

    name: str
    passed: bool
    detail: str


Fetcher = Callable[[str], tuple[int, str]]


def fetch(url: str, timeout_seconds: float = 5.0) -> tuple[int, str]:
    """GET one loopback URL without inheriting an HTTP proxy."""

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json, text/plain"})
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.status, response.read().decode("utf-8", errors="replace")


def check_metrics(api_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Require the API exposition and its stable P13 metric families."""

    try:
        status, body = fetcher(f"{api_url}/metrics")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return CheckResult("API metrics", False, f"could not reach API: {type(exc).__name__}")
    missing = [name for name in _METRIC_NAMES if name not in body]
    if status != 200:
        return CheckResult("API metrics", False, f"HTTP {status}; expected 200")
    if missing:
        return CheckResult("API metrics", False, f"missing metric families: {', '.join(missing)}")
    return CheckResult("API metrics", True, f"HTTP 200 with {len(_METRIC_NAMES)} key families")


def _json_result(name: str, url: str, fetcher: Fetcher) -> tuple[CheckResult | None, Any]:
    try:
        status, body = fetcher(url)
        payload = json.loads(body)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return CheckResult(name, False, f"invalid response: {type(exc).__name__}"), None
    if status != 200:
        return CheckResult(name, False, f"HTTP {status}; expected 200"), None
    return None, payload


def check_prometheus_ready(prometheus_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Use Prometheus's official readiness endpoint."""

    try:
        status, _ = fetcher(f"{prometheus_url}/-/ready")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return CheckResult("Prometheus ready", False, f"could not connect: {type(exc).__name__}")
    return CheckResult(
        "Prometheus ready",
        status == 200,
        "HTTP 200" if status == 200 else f"HTTP {status}; expected 200",
    )


def check_prometheus_target(prometheus_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Require the configured API scrape target to report UP."""

    error, payload = _json_result("Prometheus target", f"{prometheus_url}/api/v1/targets", fetcher)
    if error is not None:
        return error
    targets = payload.get("data", {}).get("activeTargets", []) if isinstance(payload, dict) else []
    matching = [
        target for target in targets if target.get("labels", {}).get("job") == "travel-planner-api"
    ]
    if not matching:
        return CheckResult("Prometheus target", False, "travel-planner-api target was not found")
    health = matching[0].get("health")
    return CheckResult(
        "Prometheus target",
        health == "up",
        "travel-planner-api is UP" if health == "up" else f"target health is {health!r}",
    )


def check_prometheus_query(prometheus_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Require one real query result for the API target."""

    query = urllib.parse.urlencode({"query": 'up{job="travel-planner-api"}'})
    error, payload = _json_result(
        "Prometheus query", f"{prometheus_url}/api/v1/query?{query}", fetcher
    )
    if error is not None:
        return error
    result = payload.get("data", {}).get("result", []) if isinstance(payload, dict) else []
    is_up = bool(result) and result[0].get("value", [None, "0"])[1] == "1"
    return CheckResult(
        "Prometheus query",
        is_up,
        "up query returned 1" if is_up else "up query had no successful sample",
    )


def check_grafana_health(grafana_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Require Grafana's health API to report an operational database."""

    error, payload = _json_result("Grafana health", f"{grafana_url}/api/health", fetcher)
    if error is not None:
        return error
    healthy = isinstance(payload, dict) and payload.get("database") == "ok"
    return CheckResult(
        "Grafana health", healthy, "database is ok" if healthy else "database is not ready"
    )


def check_grafana_datasource(grafana_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Verify the immutable datasource UID from file provisioning."""

    uid = "travel-planner-prometheus"
    error, payload = _json_result(
        "Grafana datasource", f"{grafana_url}/api/datasources/uid/{uid}", fetcher
    )
    if error is not None:
        return error
    valid = isinstance(payload, dict) and payload.get("uid") == uid
    return CheckResult(
        "Grafana datasource", valid, f"UID {uid}" if valid else "provisioned UID mismatch"
    )


def check_grafana_dashboard(grafana_url: str, fetcher: Fetcher = fetch) -> CheckResult:
    """Verify the provisioned dashboard UID and its required 20 panels."""

    uid = "travel-planner-overview"
    error, payload = _json_result(
        "Grafana dashboard", f"{grafana_url}/api/dashboards/uid/{uid}", fetcher
    )
    if error is not None:
        return error
    dashboard = payload.get("dashboard", {}) if isinstance(payload, dict) else {}
    panels = dashboard.get("panels", []) if isinstance(dashboard, dict) else []
    valid = dashboard.get("uid") == uid and len(panels) >= 20
    return CheckResult(
        "Grafana dashboard",
        valid,
        f"UID {uid} with {len(panels)} panels" if valid else "UID or panel count mismatch",
    )


def run_checks(api_url: str, prometheus_url: str, grafana_url: str) -> list[CheckResult]:
    """Run every local check once in a predictable order."""

    return [
        check_metrics(api_url),
        check_prometheus_ready(prometheus_url),
        check_prometheus_target(prometheus_url),
        check_prometheus_query(prometheus_url),
        check_grafana_health(grafana_url),
        check_grafana_datasource(grafana_url),
        check_grafana_dashboard(grafana_url),
    ]


def exit_code(results: Sequence[CheckResult]) -> int:
    """Return nonzero when any required component fails."""

    return 0 if all(result.passed for result in results) else 1


def parse_args() -> argparse.Namespace:
    """Read only loopback base URLs from command-line options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    return parser.parse_args()


def main() -> int:
    """Print one PASS/FAIL line per component and return a shell-friendly code."""

    args = parse_args()
    results = run_checks(
        args.api_url.rstrip("/"), args.prometheus_url.rstrip("/"), args.grafana_url.rstrip("/")
    )
    for result in results:
        prefix = "PASS" if result.passed else "FAIL"
        print(f"{prefix} {result.name}: {result.detail}")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
