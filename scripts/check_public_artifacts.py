"""Bounded current-worktree/bundle scan; never reads ignored real environment files."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "possible_qwen_key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "possible_duffel_token": re.compile(r"\bduffel_(?:test|live)_[A-Za-z0-9_-]{20,}\b"),
    "possible_jwt": re.compile(
        r"\beyJ[A-Za-z0-9_-]{12,}\.eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}"
    ),
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*"
        r"[A-Za-z0-9+/=\r\n]{48,}-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "private_vite_variable": re.compile(
        r"\bVITE_(?:QWEN|DASHSCOPE|DUFFEL|LITEAPI|DATABASE|REDIS)[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|URL)\b"
    ),
}


def inspect_text(text: str) -> list[tuple[str, int]]:
    """Return category and line number only, never matched text."""
    return [
        (name, text.count("\n", 0, match.start()) + 1)
        for name, pattern in PATTERNS.items()
        for match in pattern.finditer(text)
    ]


def forbidden_path(path: Path) -> bool:
    """Recognize real env files and private/generated artifacts, without reading them."""
    return (
        (path.name.startswith(".env") and not path.name.endswith(".example"))
        or any(
            part
            in {
                ".auth",
                ".p19-private",
                "test-results",
                "playwright-report",
                ".model-cache",
                "__pycache__",
            }
            for part in path.parts
        )
        or path.suffix in {".har", ".pt", ".safetensors", ".sqlite", ".db"}
        or str(path).startswith("data/generated/")
    )


def main() -> int:
    """Scan checked-in/candidate text plus build output, not Git history or secret values."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=10,
    )
    candidates = {Path(name) for name in listed.stdout.decode().split("\0") if name}
    bundle = ROOT / "frontend/dist"
    bundle_files = list(bundle.rglob("*")) if bundle.is_dir() else []
    candidates.update(path.relative_to(ROOT) for path in bundle_files if path.is_file())
    findings = 0
    checked = 0
    for path in sorted(candidates):
        if forbidden_path(path):
            print(f"FAIL private_artifact: {path}")
            findings += 1
            continue
        absolute = ROOT / path
        if not absolute.is_file() or absolute.suffix.lower() in {".jpg", ".jpeg", ".png", ".woff2"}:
            continue
        if absolute.is_symlink() or absolute.stat().st_size > 8_000_000:
            print(f"FAIL unscanned_file: {path}")
            findings += 1
            continue
        try:
            contents = absolute.read_text(encoding="utf-8")
        except UnicodeError:
            print(f"FAIL unscanned_encoding: {path}")
            findings += 1
            continue
        checked += 1
        for category, line in inspect_text(contents):
            print(f"FAIL {category}: {path}:{line}")
            findings += 1
    for path in (
        ".env",
        "frontend/.env.local",
        ".p19-private/auth-state.json",
        "frontend/.auth/session.json",
    ):
        ignored = (
            subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, timeout=10).returncode
            == 0
        )
        if not ignored:
            print(f"FAIL not_ignored: {path}")
            findings += 1
    print(
        f"{'PASS' if not findings else 'FAIL'} bounded scan: "
        f"{checked} text files, {findings} findings"
    )
    print(f"{'PASS' if bundle_files else 'NOT VERIFIED'} frontend bundle present")
    print(
        "NOT CONFIRMED historical key revocation: obtain provider-console confirmation separately"
    )
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
