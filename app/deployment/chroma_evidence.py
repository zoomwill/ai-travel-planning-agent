"""Read-only Chroma before/after evidence. Never restarts or repairs any service."""

import argparse
import hashlib
import json
import math
import signal
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings
from app.rag.indexer import build_advanced_corpus

MAX_RECORDS = 4096
PRIVATE_DIRECTORY = Path(".p19-private")


def _deadline_expired(signum: int, frame: object) -> None:
    """Interrupt an unavailable server on the supported macOS/Linux CLI hosts."""
    raise TimeoutError("verification_deadline")


def digest(value: object) -> str:
    """Hash canonical JSON instead of printing documents, metadata, or vectors."""
    data = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(data.encode()).hexdigest()


def snapshot(collection: Any, *, expected_ids: set[str] | None = None) -> dict[str, Any]:
    """Read bounded pages, a fixed canonical sample, and one direct vector query."""
    count = collection.count()
    if not isinstance(count, int) or not 1 <= count <= MAX_RECORDS:
        raise ValueError("collection_missing_empty_or_too_large")
    ids: list[str] = []
    for offset in range(0, count, 128):
        page = collection.get(limit=128, offset=offset, include=[])["ids"]
        if not isinstance(page, list) or not all(isinstance(item, str) for item in page):
            raise ValueError("invalid_ids")
        ids.extend(page)
    if len(ids) != count or len(set(ids)) != count or collection.count() != count:
        raise ValueError("collection_changed_during_read")
    ids.sort()
    if expected_ids is not None and set(ids) != expected_ids:
        raise ValueError("collection_differs_from_current_corpus")
    sample = collection.get(ids=ids[:5], include=["documents", "metadatas"])
    records = sorted(zip(sample["ids"], sample["documents"], sample["metadatas"], strict=True))
    if {row[0] for row in records} != set(ids[:5]) or any(not row[1] for row in records):
        raise ValueError("invalid_sample")
    # Same fixed query after reconnect: canonical first ID's persisted vector.
    # Never use `or` on NumPy arrays, load a model, or write/query through Redis.
    embedding = collection.get(ids=[ids[0]], include=["embeddings"])["embeddings"]
    if embedding is None or len(embedding) != 1:
        raise ValueError("query_embedding_unavailable")
    vector = [float(value) for value in embedding[0]]
    if not 1 <= len(vector) <= 8192 or not all(math.isfinite(x) for x in vector):
        raise ValueError("invalid_query_embedding")
    result = collection.query(
        query_embeddings=[vector], n_results=min(5, count), include=["distances"]
    )
    result_ids = result["ids"][0]
    distances = result["distances"][0]
    if (
        len(result_ids) != min(5, count)
        or len(set(result_ids)) != len(result_ids)
        or not set(result_ids) <= set(ids)
        or ids[0] not in result_ids
        or len(distances) != len(result_ids)
        or not all(math.isfinite(x) for x in distances)
    ):
        raise ValueError("direct_query_invalid")
    if collection.count() != count:
        raise ValueError("collection_changed_during_read")
    return {
        "schema_version": 1,
        "exists": True,
        "count": count,
        "ids_sha256": digest(ids),
        "metadata_sha256": digest(collection.metadata),
        "sample_sha256": digest(records),
        "query_vector_sha256": digest(vector),
        "embedding_dimension": len(vector),
        "query_ids_sha256": digest(sorted(result_ids)),
        "query_anchor_sha256": digest(ids[0]),
        "query_valid": True,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Require data identity, allowing approximate neighbor order and float distances."""
    keys = (
        "schema_version",
        "exists",
        "count",
        "ids_sha256",
        "metadata_sha256",
        "sample_sha256",
        "query_vector_sha256",
        "embedding_dimension",
        "query_anchor_sha256",
        "context_sha256",
        "pipeline_sha256",
        "model_sha256",
        "endpoint_sha256",
    )
    return (
        before.get("query_valid") is True
        and after.get("query_valid") is True
        and all(key in before and before[key] == after.get(key) for key in keys)
    )


def _run_check() -> int:
    """Print sanitized evidence; save only hashes to an explicitly ignored local file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--baseline", type=Path, required=True, help="File inside .p19-private/")
    parser.add_argument(
        "--context", required=True, help="Non-secret service/environment/volume label"
    )
    args = parser.parse_args()
    previous_handler = signal.signal(signal.SIGALRM, _deadline_expired)
    signal.alarm(60)
    try:
        if not args.baseline.resolve().is_relative_to(PRIVATE_DIRECTORY.resolve()):
            raise ValueError("baseline_must_be_private")
        settings = Settings()
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            ssl=settings.chroma_ssl,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_collection(
            name=settings.rag_child_collection, embedding_function=None
        )
        current = snapshot(collection)
        if (collection.metadata or {}).get("pipeline_version") != settings.rag_pipeline_version:
            raise ValueError("collection_pipeline_mismatch")
        corpus = build_advanced_corpus(settings, embedding_dimension=current["embedding_dimension"])
        expected = sorted(child.child_id for child in corpus.children)
        if current["ids_sha256"] != digest(expected):
            raise ValueError("collection_differs_from_current_corpus")
        current.update(
            observed_at=datetime.now(UTC).isoformat(),
            context_sha256=digest(args.context),
            pipeline_sha256=digest(settings.rag_pipeline_version),
            model_sha256=digest([settings.rag_embedding_model, settings.rag_embedding_revision]),
            endpoint_sha256=digest(
                [
                    settings.chroma_host,
                    settings.chroma_port,
                    settings.chroma_ssl,
                    settings.rag_child_collection,
                ]
            ),
        )
        if args.phase == "before":
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            with args.baseline.open("x", encoding="utf-8") as output:
                json.dump(current, output, sort_keys=True, indent=2)
            print("PASS baseline: existing collection and direct query recorded")
        else:
            if args.baseline.stat().st_size > 32768:
                raise ValueError("invalid_baseline_size")
            before = json.loads(args.baseline.read_text(encoding="utf-8"))
            if not compare(before, current):
                raise ValueError("before_after_data_mismatch")
            print("PASS data comparison: unchanged IDs/sample/metadata/query anchor")
        print(json.dumps(current, sort_keys=True))
        print(
            "NOT VERIFIED restart: independently prove Chroma-only restart "
            "and no API bootstrap/reindex"
        )
        return 0
    except Exception as error:
        # Provider/Settings errors may contain URLs, values, or credentials.
        safe_codes = {
            "collection_missing_empty_or_too_large",
            "invalid_ids",
            "invalid_sample",
            "query_embedding_unavailable",
            "invalid_query_embedding",
            "direct_query_invalid",
            "collection_changed_during_read",
            "collection_differs_from_current_corpus",
            "baseline_must_be_private",
            "before_after_data_mismatch",
            "collection_pipeline_mismatch",
            "invalid_baseline_size",
        }
        code = (
            str(error) if type(error) is ValueError and str(error) in safe_codes else "read_failed"
        )
        if isinstance(error, TimeoutError):
            code = "verification_deadline"
        print(f"FAIL read-only verification: {code}; no repair attempted")
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def run_with_deadline(command: Sequence[str], *, timeout: float = 70) -> int:
    """Supervise our own worker; timeout kills and reaps it, not merely its waiter."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("FAIL read-only verification: verification_deadline; worker killed and reaped")
        return 1
    except KeyboardInterrupt:
        print("STOP read-only verification: cancelled; worker stopped")
        return 130
    except OSError:
        print("FAIL read-only verification: worker_unavailable")
        return 1
    if result.stdout:
        print(result.stdout, end="")
    elif result.returncode:
        print("FAIL read-only verification: worker_exited")
    return result.returncode


def main() -> int:
    """Run the read-only worker with a process-level deadline on macOS/Linux."""
    return run_with_deadline(
        [sys.executable, "-m", "app.deployment.chroma_evidence", "--worker", *sys.argv[1:]]
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        del sys.argv[1]
        raise SystemExit(_run_check())
    raise SystemExit(main())
