"""Check the local Phase P01 Docker infrastructure.

This script deliberately uses Docker commands and Python's standard library. It does
not install or import the application database clients reserved for Phase P02.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    """Store one infrastructure check result without any credentials."""

    name: str
    passed: bool
    detail: str


Check = Callable[[], CheckResult]
Sleeper = Callable[[float], None]


def evaluate_command(
    name: str,
    returncode: int,
    stdout: str,
    stderr: str,
    expected_text: str,
) -> CheckResult:
    """Convert command output into a beginner-readable PASS or FAIL result."""

    clean_stdout = stdout.strip()
    clean_stderr = stderr.strip()
    if returncode != 0:
        detail = clean_stderr or clean_stdout or f"command exited with code {returncode}"
        return CheckResult(name, False, detail)

    if expected_text.casefold() not in clean_stdout.casefold():
        detail = clean_stdout or "command returned no output"
        return CheckResult(name, False, f"expected {expected_text!r}; received: {detail}")

    return CheckResult(name, True, clean_stdout)


def evaluate_http(name: str, status: int, body: str) -> CheckResult:
    """Convert an HTTP response into a beginner-readable PASS or FAIL result."""

    clean_body = body.strip()
    if status != 200:
        return CheckResult(name, False, f"HTTP {status}; expected HTTP 200")
    if not clean_body:
        return CheckResult(name, False, "HTTP 200 response body was empty")
    return CheckResult(name, True, f"HTTP 200: {clean_body}")


def read_dotenv_value(name: str, path: Path | None = None) -> str | None:
    """Read one named, non-secret setting without loading every value from .env."""

    dotenv_path = path if path is not None else Path(".env")
    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if separator and key.strip() == name:
            clean_value = value.strip()
            if (
                len(clean_value) >= 2
                and clean_value[0] == clean_value[-1]
                and clean_value[0] in {'"', "'"}
            ):
                return clean_value[1:-1]
            return clean_value
    return None


def run_command(
    command: Sequence[str], timeout_seconds: float = 10.0
) -> subprocess.CompletedProcess[str]:
    """Run one command with captured output and a finite timeout."""

    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )


def check_postgres() -> CheckResult:
    """Ask pg_isready inside the PostgreSQL container for connection status."""

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
    ]
    try:
        completed = run_command(command)
    except FileNotFoundError:
        return CheckResult("PostgreSQL", False, "docker command was not found")
    except subprocess.TimeoutExpired:
        return CheckResult("PostgreSQL", False, "pg_isready timed out after 10 seconds")
    return evaluate_command(
        "PostgreSQL",
        completed.returncode,
        completed.stdout,
        completed.stderr,
        "accepting connections",
    )


def check_redis() -> CheckResult:
    """Ask redis-cli inside the Redis container for its PONG response."""

    command = ["docker", "compose", "exec", "-T", "redis", "redis-cli", "ping"]
    try:
        completed = run_command(command)
    except FileNotFoundError:
        return CheckResult("Redis", False, "docker command was not found")
    except subprocess.TimeoutExpired:
        return CheckResult("Redis", False, "redis-cli ping timed out after 10 seconds")
    return evaluate_command(
        "Redis",
        completed.returncode,
        completed.stdout,
        completed.stderr,
        "PONG",
    )


def check_chroma() -> CheckResult:
    """Call Chroma's official API v2 health endpoint from the host."""

    try:
        host = os.getenv("CHROMA_HOST") or read_dotenv_value("CHROMA_HOST") or "127.0.0.1"
        port = os.getenv("CHROMA_PORT") or read_dotenv_value("CHROMA_PORT") or "8001"
    except OSError as error:
        return CheckResult("Chroma", False, f"could not read .env: {error.strerror or error}")
    if not port.isdecimal():
        return CheckResult("Chroma", False, "CHROMA_PORT must contain only digits")

    url = f"http://{host}:{port}/api/v2/healthcheck"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as response:  # noqa: S310
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return CheckResult("Chroma", False, f"HTTP {error.code} from {url}")
    except urllib.error.URLError as error:
        return CheckResult("Chroma", False, f"could not reach {url}: {error.reason}")
    except TimeoutError:
        return CheckResult("Chroma", False, f"request to {url} timed out after 5 seconds")
    return evaluate_http("Chroma", status, body)


def run_with_retries(
    check: Check,
    attempts: int,
    delay_seconds: float,
    sleep: Sleeper = time.sleep,
) -> CheckResult:
    """Retry a failing check so slowly starting containers have time to become ready."""

    result = check()
    for _ in range(1, attempts):
        if result.passed:
            return result
        sleep(delay_seconds)
        result = check()
    return result


def exit_code(results: Sequence[CheckResult]) -> int:
    """Return zero only when every infrastructure check passed."""

    return 0 if all(result.passed for result in results) else 1


def parse_args() -> argparse.Namespace:
    """Read retry settings from command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--attempts",
        type=int,
        default=15,
        help="maximum attempts per service (default: 15)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds between attempts (default: 2)",
    )
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    return args


def main() -> int:
    """Run all infrastructure checks, print results, and return a shell exit code."""

    args = parse_args()
    checks: tuple[Check, ...] = (check_postgres, check_redis, check_chroma)
    results = [run_with_retries(check, args.attempts, args.delay) for check in checks]

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.name}: {result.detail}")

    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
