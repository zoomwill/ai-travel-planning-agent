"""Scanner reports locations, never credential values; revocation is not inferred."""

from pathlib import Path

import pytest

from scripts.check_public_artifacts import forbidden_path, inspect_text


def test_detects_synthetic_keys_without_returning_values():
    synthetic = "sk-" + "A" * 32
    assert inspect_text("line one\n" + synthetic) == [("possible_qwen_key", 2)]
    assert synthetic not in repr(inspect_text(synthetic))


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "frontend/.env.local",
        "frontend/.auth/state.json",
        ".p19-private/session.json",
        "data/generated/index.json",
        "frontend/test-results/trace.zip",
    ],
)
def test_private_files_are_rejected_before_read(path):
    assert forbidden_path(Path(path))


def test_examples_and_selected_images_are_allowed():
    assert not forbidden_path(Path(".env.example"))
    assert not forbidden_path(Path("frontend/.env.example"))
    assert not forbidden_path(Path("docs/images/p19-01.jpg"))


def test_key_parser_delimiter_alone_is_not_a_credential_but_complete_pem_is_detected():
    begin = "-----BEGIN PRIVATE KEY-----"
    end = "-----END PRIVATE KEY-----"
    assert inspect_text(begin) == []
    synthetic = begin + "\n" + "A" * 64 + "\n" + end
    assert inspect_text(synthetic) == [("private_key", 1)]
    assert synthetic not in repr(inspect_text(synthetic))
