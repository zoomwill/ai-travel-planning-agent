"""Canonical SHA-256 helpers for persistent P10 identifiers and fingerprints."""

import hashlib
import json
from collections.abc import Sequence


def canonical_json(value: object) -> str:
    """Serialize supported values with stable keys and separators."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(value: str) -> str:
    """Return a lowercase SHA-256 hexadecimal digest for UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: object) -> str:
    """Hash canonical JSON rather than Python's process-specific hash function."""

    return sha256_text(canonical_json(value))


def corpus_fingerprint(
    *,
    parent_ids: Sequence[str],
    child_ids: Sequence[str],
    pipeline_version: str,
    embedding_model: str,
) -> str:
    """Fingerprint the exact sorted corpus and configuration identity."""

    payload: dict[str, object] = {
        "child_ids": sorted(child_ids),
        "embedding_model": embedding_model,
        "parent_ids": sorted(parent_ids),
        "pipeline_version": pipeline_version,
    }
    return canonical_sha256(payload)
