"""Pure checker tests that never require Docker or network access."""

import json

from scripts.check_observability import (
    CheckResult,
    check_grafana_dashboard,
    check_prometheus_target,
    exit_code,
)


def test_prometheus_target_requires_named_target_to_be_up() -> None:
    payload = {
        "data": {
            "activeTargets": [
                {"labels": {"job": "travel-planner-api"}, "health": "up"},
            ]
        }
    }
    result = check_prometheus_target(
        "http://prometheus",
        lambda _: (200, json.dumps(payload)),
    )
    assert result == CheckResult("Prometheus target", True, "travel-planner-api is UP")

    payload["data"]["activeTargets"][0]["health"] = "down"
    failed = check_prometheus_target(
        "http://prometheus",
        lambda _: (200, json.dumps(payload)),
    )
    assert failed.passed is False


def test_dashboard_requires_fixed_uid_and_twenty_eight_panels() -> None:
    valid = {
        "dashboard": {
            "uid": "travel-planner-overview",
            "panels": [{"id": index} for index in range(1, 29)],
        }
    }
    result = check_grafana_dashboard("http://grafana", lambda _: (200, json.dumps(valid)))
    assert result.passed is True
    assert "28 panels" in result.detail

    valid["dashboard"]["panels"].pop()
    failed = check_grafana_dashboard("http://grafana", lambda _: (200, json.dumps(valid)))
    assert failed.passed is False


def test_exit_code_reports_any_failure() -> None:
    assert exit_code([CheckResult("one", True, "ok")]) == 0
    assert exit_code([CheckResult("one", False, "not ready")]) == 1
