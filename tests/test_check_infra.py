"""Unit tests for infrastructure-checking logic without requiring Docker."""

from collections.abc import Iterator
from pathlib import Path

from scripts.check_infra import (
    CheckResult,
    evaluate_command,
    evaluate_http,
    exit_code,
    read_dotenv_value,
    run_with_retries,
)


def test_evaluate_command_accepts_expected_output() -> None:
    result = evaluate_command("Redis", 0, "PONG\n", "", "PONG")

    assert result == CheckResult("Redis", True, "PONG")


def test_evaluate_command_explains_nonzero_exit() -> None:
    result = evaluate_command("PostgreSQL", 1, "", "container is not running", "accepting")

    assert result == CheckResult("PostgreSQL", False, "container is not running")


def test_evaluate_command_rejects_unexpected_output() -> None:
    result = evaluate_command("Redis", 0, "LOADING\n", "", "PONG")

    assert result.passed is False
    assert "expected 'PONG'" in result.detail


def test_evaluate_http_accepts_nonempty_200_response() -> None:
    result = evaluate_http("Chroma", 200, '"ok"')

    assert result == CheckResult("Chroma", True, 'HTTP 200: "ok"')


def test_evaluate_http_rejects_error_status() -> None:
    result = evaluate_http("Chroma", 503, '"unavailable"')

    assert result == CheckResult("Chroma", False, "HTTP 503; expected HTTP 200")


def test_evaluate_http_rejects_empty_body() -> None:
    result = evaluate_http("Chroma", 200, "  ")

    assert result == CheckResult("Chroma", False, "HTTP 200 response body was empty")


def test_read_dotenv_value_reads_only_requested_name(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# local ports\nCHROMA_HOST=127.0.0.1\nCHROMA_PORT='9001'\n",
        encoding="utf-8",
    )

    assert read_dotenv_value("CHROMA_PORT", dotenv) == "9001"
    assert read_dotenv_value("MISSING", dotenv) is None


def test_read_dotenv_value_allows_missing_file(tmp_path: Path) -> None:
    assert read_dotenv_value("CHROMA_PORT", tmp_path / "missing.env") is None


def test_run_with_retries_stops_after_success() -> None:
    results: Iterator[CheckResult] = iter(
        [
            CheckResult("Chroma", False, "starting"),
            CheckResult("Chroma", True, 'HTTP 200: "ok"'),
        ]
    )
    sleeps: list[float] = []

    result = run_with_retries(lambda: next(results), 3, 0.5, sleeps.append)

    assert result.passed is True
    assert sleeps == [0.5]


def test_exit_code_is_nonzero_when_any_check_fails() -> None:
    results = [
        CheckResult("PostgreSQL", True, "accepting connections"),
        CheckResult("Redis", False, "connection refused"),
    ]

    assert exit_code(results) == 1
    assert exit_code([CheckResult("Redis", True, "PONG")]) == 0
