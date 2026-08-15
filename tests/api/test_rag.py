"""Docker-free HTTP tests for local P10 RAG diagnostics."""

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from app.rag.advanced_retriever import AdvancedRetriever
from app.rag.models import AdvancedRetrievalResult, QueryBundle, RetrievalDiagnostics
from app.rag.runtime import AdvancedRagRuntime, UnavailableAdvancedRetriever
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


class FakeAdvancedRetriever:
    """Return one safe Paris parent and record validated query bundles."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.bundles: list[QueryBundle] = []

    async def retrieve(self, query_bundle: QueryBundle, **kwargs: object):
        del kwargs
        self.bundles.append(query_bundle)
        if self.fail:
            raise RuntimeError("private vector-store secret")
        return AdvancedRetrievalResult(
            contexts=["Source: paris.md\nTitle: Paris museums\n\nUse one anchor museum."],
            parent_ids=["paris-parent"],
            query_variants=[query_bundle.original_query],
            diagnostics=RetrievalDiagnostics(
                pipeline_version="advanced-v1",
                corpus_fingerprint="f" * 64,
                embedding_backend="sentence_transformers",
                embedding_model="test-model",
                query_variant_count=1,
                dense_candidate_count=2,
                sparse_candidate_count=2,
                fused_candidate_count=2,
                reranked_candidate_count=1,
                returned_parent_count=1,
                metadata_filter_applied=True,
                metadata_filter_fallback_used=False,
                cache_status="miss",
            ),
        )


def make_client(
    *,
    indexed: bool = True,
    fail: bool = False,
) -> tuple[TestClient, FakeAdvancedRetriever]:
    """Start FastAPI with only in-memory/fake P10 dependencies."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)
    retriever = FakeAdvancedRetriever(fail=fail)
    runtime_retriever: AdvancedRetriever = (
        cast(AdvancedRetriever, retriever) if indexed else UnavailableAdvancedRetriever(settings)
    )
    fakes.resources.rag_runtime = AdvancedRagRuntime(
        pipeline_version="advanced-v1",
        indexed=indexed,
        collection_name="travel_knowledge_children_v1",
        child_count=77 if indexed else 0,
        parent_count=36 if indexed else 0,
        corpus_fingerprint="f" * 64 if indexed else "",
        embedding_model="test-model",
        embedding_dimension=384 if indexed else 0,
        bm25_ready=indexed,
        retriever=runtime_retriever,
    )

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    app = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    return TestClient(app), retriever


@pytest.fixture
def rag_client() -> Iterator[tuple[TestClient, FakeAdvancedRetriever]]:
    """Yield one indexed local-development client."""

    client, retriever = make_client()
    with client:
        yield client, retriever


def test_rag_status_returns_only_safe_index_facts(
    rag_client: tuple[TestClient, FakeAdvancedRetriever],
) -> None:
    """Status reports readiness and counts without URLs, paths, or secrets."""

    client, _ = rag_client
    response = client.get("/api/v1/rag/status")

    assert response.status_code == 200
    assert response.json()["indexed"] is True
    assert response.json()["child_count"] == 77
    assert response.json()["parent_count"] == 36
    assert "password" not in response.text.casefold()
    assert "model-cache" not in response.text.casefold()


def test_rag_search_returns_parent_context_without_vectors(
    rag_client: tuple[TestClient, FakeAdvancedRetriever],
) -> None:
    """Validated request fields reach the retriever and the response stays bounded."""

    client, retriever = rag_client
    response = client.post(
        "/api/v1/rag/search",
        json={
            "query": "Paris museum day",
            "destination": "Paris",
            "preferences": ["museums"],
            "top_k": 4,
        },
    )

    assert response.status_code == 200
    assert response.json()["parent_ids"] == ["paris-parent"]
    assert retriever.bundles[0].destination == "Paris"
    assert retriever.bundles[0].current_preferences == ["museums"]
    assert "embedding_backend" in response.text
    assert "embedding_values" not in response.text
    assert "traceback" not in response.text.casefold()


def test_unindexed_and_internal_failure_return_sanitized_503() -> None:
    """Neither missing preparation nor a private exception leaks implementation detail."""

    unindexed_client, _ = make_client(indexed=False)
    failing_client, _ = make_client(fail=True)
    payload = {"query": "Tokyo", "destination": "Tokyo", "top_k": 4}
    with unindexed_client:
        unindexed = unindexed_client.post("/api/v1/rag/search", json=payload)
    with failing_client:
        failing = failing_client.post("/api/v1/rag/search", json=payload)

    assert unindexed.status_code == 503
    assert unindexed.json()["detail"]["code"] == "rag_not_indexed"
    assert failing.status_code == 503
    assert failing.json()["detail"]["code"] == "retrieval_unavailable"
    assert "private vector-store secret" not in failing.text
