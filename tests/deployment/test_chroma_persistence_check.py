"""Pure read-only evidence checks: no running Docker, model, or Redis required."""

import copy
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.config import Settings
from app.deployment import chroma_evidence
from app.deployment.chroma_evidence import compare, digest, run_with_deadline, snapshot


class Collection:
    metadata = {"pipeline_version": "advanced-v1"}

    def __init__(self):
        self.rows = {
            key: {"document": "Knowledge " + key, "metadata": {"index_version": "advanced-v1"}}
            for key in ("c", "b", "a")
        }
        self.queries = 0

    def count(self):
        return len(self.rows)

    def get(self, *, ids=None, include, limit=None, offset=0):
        chosen = ids if ids is not None else list(self.rows)[offset : offset + limit]
        return {
            "ids": chosen,
            "documents": [self.rows[k]["document"] for k in chosen],
            "metadatas": [self.rows[k]["metadata"] for k in chosen],
            "embeddings": np.array([[0.1, 0.2, 0.3]]) if "embeddings" in include else None,
        }

    def query(self, *, query_embeddings, n_results, include):
        assert query_embeddings == [[0.1, 0.2, 0.3]]
        self.queries += 1
        return {"ids": [["a", "b", "c"]], "distances": [[0.0, 0.1, 0.2]]}


def complete_snapshot(collection):
    result = snapshot(collection, expected_ids={"a", "b", "c"})
    result.update(
        context_sha256=digest("test/service/volume"),
        pipeline_sha256=digest("advanced-v1"),
        model_sha256=digest("configured model"),
        endpoint_sha256=digest("same endpoint"),
    )
    return result


def test_reconnect_same_records_and_direct_query_without_vectors_in_output():
    first, second = Collection(), Collection()
    before, after = complete_snapshot(first), complete_snapshot(second)
    assert first is not second and first.queries == second.queries == 1
    assert compare(before, after)
    assert "Knowledge" not in str(before) and "0.1" not in str(before)
    after["query_ids_sha256"] = digest(["c", "b", "a"])
    assert compare(before, after)  # Query order / approximate ranking is not identity.


@pytest.mark.parametrize(
    "key",
    [
        "ids_sha256",
        "sample_sha256",
        "metadata_sha256",
        "count",
        "query_vector_sha256",
        "context_sha256",
        "endpoint_sha256",
    ],
)
def test_changed_or_missing_evidence_fails(key):
    before = complete_snapshot(Collection())
    after = copy.deepcopy(before)
    after[key] = "changed"
    assert not compare(before, after)
    del after[key]
    assert not compare(before, after)


def test_content_change_caught_and_unexpected_corpus_not_repaired():
    collection = Collection()
    before = complete_snapshot(collection)
    collection.rows["b"]["document"] = "Different knowledge"
    assert not compare(before, complete_snapshot(collection))
    with pytest.raises(ValueError, match="corpus"):
        snapshot(collection, expected_ids={"another"})
    assert collection.count() == 3


def test_empty_collection_and_query_outside_original_ids_rejected():
    empty = Collection()
    empty.rows = {}
    with pytest.raises(ValueError):
        snapshot(empty)
    invalid = Collection()
    invalid.query = lambda **kwargs: {"ids": [["x", "y", "z"]], "distances": [[0, 1, 2]]}
    with pytest.raises(ValueError, match="direct_query"):
        snapshot(invalid)


def test_process_deadline_kills_blocked_worker_and_does_not_print_partial_output(capsys):
    command = [
        sys.executable,
        "-c",
        "import time; print('private data', flush=True); time.sleep(30)",
    ]
    assert run_with_deadline(command, timeout=0.1) == 1
    output = capsys.readouterr().out
    assert "worker killed and reaped" in output
    assert "private data" not in output


def test_worker_failure_never_forwards_stderr(capsys):
    assert run_with_deadline([sys.executable, "-c", "raise RuntimeError('private exception')"]) != 0
    output = capsys.readouterr().out
    assert "worker_exited" in output and "private exception" not in output


def test_cli_reads_existing_collection_twice_and_saves_only_summaries(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    collections = []

    class ReadOnlyClient:
        def get_collection(self, *, name, embedding_function):
            assert name == settings.rag_child_collection and embedding_function is None
            collection = Collection()
            collection.metadata = {"pipeline_version": settings.rag_pipeline_version}
            collections.append(collection)
            return collection

    monkeypatch.setattr(chroma_evidence, "Settings", lambda: settings)
    monkeypatch.setattr(chroma_evidence.chromadb, "HttpClient", lambda **kwargs: ReadOnlyClient())
    monkeypatch.setattr(
        chroma_evidence,
        "build_advanced_corpus",
        lambda *args, **kwargs: SimpleNamespace(
            children=[SimpleNamespace(child_id=key) for key in ("a", "b", "c")]
        ),
    )
    baseline = tmp_path / ".p19-private" / "baseline.json"
    for phase in ("before", "after"):
        monkeypatch.setattr(
            sys, "argv", ["check", phase, "--baseline", str(baseline), "--context", "local-test"]
        )
        assert chroma_evidence._run_check() == 0
    assert len(collections) == 2 and all(c.queries == 1 for c in collections)
    saved = baseline.read_text()
    assert json.loads(saved)["observed_at"]
    assert "Knowledge" not in saved and "embeddings" not in saved
    output = capsys.readouterr().out
    assert "PASS data comparison" in output and "NOT VERIFIED restart" in output
