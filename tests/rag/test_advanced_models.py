"""Pure tests for P10 JSON models, canonical IDs, and corpus fingerprints."""

from app.rag.identity import canonical_json, canonical_sha256, corpus_fingerprint


def test_canonical_hash_ignores_mapping_insertion_order() -> None:
    """Equivalent JSON objects receive the same persistent identifier."""

    first = {"city": "Tokyo", "content": "Yanaka"}
    second = {"content": "Yanaka", "city": "Tokyo"}

    assert canonical_json(first) == canonical_json(second)
    assert canonical_sha256(first) == canonical_sha256(second)


def test_content_change_changes_persistent_hash() -> None:
    """A changed knowledge passage cannot silently reuse the old ID."""

    assert canonical_sha256({"content": "Yanaka"}) != canonical_sha256({"content": "Asakusa"})


def test_corpus_fingerprint_is_sorted_but_configuration_sensitive() -> None:
    """Input ordering is irrelevant while the embedding model remains part of identity."""

    first = corpus_fingerprint(
        parent_ids=["b", "a"],
        child_ids=["d", "c"],
        pipeline_version="advanced-v1",
        embedding_model="model-a",
    )
    reordered = corpus_fingerprint(
        parent_ids=["a", "b"],
        child_ids=["c", "d"],
        pipeline_version="advanced-v1",
        embedding_model="model-a",
    )
    changed = corpus_fingerprint(
        parent_ids=["a", "b"],
        child_ids=["c", "d"],
        pipeline_version="advanced-v1",
        embedding_model="model-b",
    )

    assert first == reordered
    assert first != changed
