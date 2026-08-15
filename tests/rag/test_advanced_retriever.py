"""Offline orchestration and graceful-degradation tests for P10."""

from typing import cast

import pytest

from app.core.config import Settings
from app.rag.advanced_retriever import AdvancedTravelRetriever
from app.rag.bm25 import BM25SparseIndex
from app.rag.cache import RedisRetrievalCache
from app.rag.models import QueryBundle, RetrievalCandidate
from app.rag.multi_query import DeterministicTravelQueryExpander
from app.rag.parent_store import LocalManifestParentStore
from app.rag.reranker import CandidateReranker, DeterministicFeatureReranker
from tests.rag.helpers import make_child, make_parent


class MemoryCacheClient:
    """Keep final JSON in memory while recording exact cache commands."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        assert ex == 3600
        self.values[name] = value
        return True

    async def delete(self, *names: str) -> int:
        for name in names:
            self.values.pop(name, None)
        return len(names)


class FakeDenseStore:
    """Return one candidate per variant or raise a private failure."""

    def __init__(self, child_id: str, parent_id: str, *, fail: bool = False) -> None:
        self.child_id = child_id
        self.parent_id = parent_id
        self.fail = fail
        self.calls = 0

    def search(
        self,
        query: str,
        *,
        query_variant: str,
        top_k: int,
        city: str | None,
    ) -> tuple[list[RetrievalCandidate], bool]:
        del query, top_k
        self.calls += 1
        if self.fail:
            raise RuntimeError("private dense detail")
        return (
            [
                RetrievalCandidate(
                    child_id=self.child_id,
                    parent_id=self.parent_id,
                    source="tokyo.md",
                    city=city or "General",
                    content="small child evidence",
                    retrieval_method="dense",
                    query_variant=query_variant,
                    rank=1,
                    raw_score=-0.1,
                )
            ],
            False,
        )


class FailingSparseIndex:
    """Raise one stable test exception from sparse retrieval."""

    def search(self, *args: object, **kwargs: object) -> list[RetrievalCandidate]:
        raise RuntimeError(f"private sparse detail {args} {kwargs}")


class FailingReranker:
    """Prove an exception falls back to parent RRF ordering."""

    async def rerank(self, **kwargs: object):
        raise RuntimeError(f"private reranker detail {kwargs}")


def build_retriever(
    *,
    dense_fail: bool = False,
    sparse_fail: bool = False,
    reranker_fail: bool = False,
    cache: RedisRetrievalCache | None = None,
) -> tuple[AdvancedTravelRetriever, FakeDenseStore]:
    """Assemble one offline advanced retriever around real pure algorithms."""

    parent = make_parent(
        "p",
        city="Tokyo",
        content="Tokyo quiet street photography neighborhoods avoid crowds.",
    )
    child = make_child(
        "c",
        parent=parent,
        content="Tokyo quiet street photography neighborhoods avoid crowds.",
    )
    dense = FakeDenseStore(child.child_id, parent.parent_id, fail=dense_fail)
    sparse = FailingSparseIndex() if sparse_fail else BM25SparseIndex([child])
    reranker: CandidateReranker = (
        cast(CandidateReranker, FailingReranker())
        if reranker_fail
        else DeterministicFeatureReranker()
    )
    settings = Settings(
        _env_file=None,
        rag_dense_top_k=4,
        rag_sparse_top_k=4,
        rag_fusion_top_k=4,
        rag_rerank_top_k=4,
        rag_final_parent_k=2,
    )
    retriever = AdvancedTravelRetriever(
        settings=settings,
        corpus_fingerprint="f" * 64,
        query_expander=DeterministicTravelQueryExpander(variant_count=2),
        dense_store=cast(object, dense),
        sparse_index=cast(object, sparse),
        parent_store=LocalManifestParentStore([parent]),
        reranker=reranker,
        cache=cache,
    )
    return retriever, dense


def bundle() -> QueryBundle:
    """Return one query with current and remembered preferences."""

    return QueryBundle(
        original_query="Tokyo quiet street photography",
        destination="Tokyo",
        current_preferences=["photography"],
        remembered_preferences=["avoid crowds"],
    )


@pytest.mark.asyncio
async def test_hybrid_runs_dense_sparse_and_returns_full_parent() -> None:
    """Final context is parent text and bounded diagnostics omit child vectors."""

    retriever, dense = build_retriever()

    result = await retriever.retrieve(bundle())

    assert result.error is None
    assert dense.calls == 2
    assert result.diagnostics.dense_candidate_count == 2
    assert result.diagnostics.sparse_candidate_count == 2
    assert result.diagnostics.returned_parent_count == 1
    assert "Source:" in result.contexts[0]
    assert "small child evidence" not in result.contexts[0]
    assert len(result.parent_ids) == len(set(result.parent_ids))


@pytest.mark.asyncio
async def test_dense_failure_degrades_to_sparse_and_reranker_failure_uses_rrf() -> None:
    """Either failure remains usable and appears only as a component name."""

    dense_retriever, _ = build_retriever(dense_fail=True)
    reranker_retriever, _ = build_retriever(reranker_fail=True)

    sparse_result = await dense_retriever.retrieve(bundle())
    fallback_result = await reranker_retriever.retrieve(bundle())

    assert sparse_result.error is None
    assert sparse_result.diagnostics.degraded_components == ["dense"]
    assert sparse_result.diagnostics.sparse_candidate_count > 0
    assert fallback_result.error is None
    assert fallback_result.diagnostics.degraded_components == ["reranker"]
    assert fallback_result.contexts


@pytest.mark.asyncio
async def test_both_retrievers_fail_without_fabricating_context() -> None:
    """No parent is invented when dense and sparse are both unavailable."""

    retriever, _ = build_retriever(dense_fail=True, sparse_fail=True)

    result = await retriever.retrieve(bundle())

    assert result.error == "retrieval_unavailable"
    assert result.contexts == []
    assert result.parent_ids == []
    assert result.diagnostics.degraded_components == ["dense", "retrieval", "sparse"]


@pytest.mark.asyncio
async def test_cache_hit_skips_every_retrieval_stage() -> None:
    """The second identical query returns final JSON without another dense call."""

    cache = RedisRetrievalCache(MemoryCacheClient(), ttl_seconds=3600)
    retriever, dense = build_retriever(cache=cache)

    first = await retriever.retrieve(bundle())
    calls_after_miss = dense.calls
    second = await retriever.retrieve(bundle())

    assert first.diagnostics.cache_status == "miss"
    assert second.diagnostics.cache_status == "hit"
    assert dense.calls == calls_after_miss == 2
    assert second.parent_ids == first.parent_ids
