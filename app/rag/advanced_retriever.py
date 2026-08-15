"""Advanced P10 retrieval orchestration with bounded deterministic degradation."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.core.config import Settings
from app.rag.advanced_vector_store import AdvancedChromaVectorStore
from app.rag.bm25 import BM25SparseIndex
from app.rag.cache import RedisRetrievalCache, build_retrieval_cache_key
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.models import (
    AdvancedRetrievalResult,
    CacheStatus,
    FusedCandidate,
    ParentDocument,
    QueryBundle,
    RerankedParent,
    RetrievalCandidate,
    RetrievalDiagnostics,
    RetrievalMode,
)
from app.rag.multi_query import QueryExpander
from app.rag.parent_store import ParentDocumentStore
from app.rag.reranker import CandidateReranker


class AdvancedRetriever(Protocol):
    """Async parent-level retrieval surface injected into LangGraph and FastAPI."""

    async def retrieve(
        self,
        query_bundle: QueryBundle,
        *,
        top_k: int | None = None,
        mode: RetrievalMode = "hybrid_reranked",
        use_cache: bool = True,
    ) -> AdvancedRetrievalResult:
        """Return final parent context with safe diagnostics."""


class AdvancedTravelRetriever:
    """Coordinate expansion, two retrieval methods, RRF, parents, reranking, and cache."""

    def __init__(
        self,
        *,
        settings: Settings,
        corpus_fingerprint: str,
        query_expander: QueryExpander,
        dense_store: AdvancedChromaVectorStore,
        sparse_index: BM25SparseIndex,
        parent_store: ParentDocumentStore,
        reranker: CandidateReranker,
        cache: RedisRetrievalCache | None,
    ) -> None:
        self._settings = settings
        self._corpus_fingerprint = corpus_fingerprint
        self._query_expander = query_expander
        self._dense_store = dense_store
        self._sparse_index = sparse_index
        self._parent_store = parent_store
        self._reranker = reranker
        self._cache = cache

    async def retrieve(
        self,
        query_bundle: QueryBundle,
        *,
        top_k: int | None = None,
        mode: RetrievalMode = "hybrid_reranked",
        use_cache: bool = True,
    ) -> AdvancedRetrievalResult:
        """Run one bounded pipeline and retain only parent-level results."""

        variants = await self._query_expander.expand(query_bundle)
        metadata_filter = {"city": query_bundle.destination} if query_bundle.destination else {}
        expanded_bundle = query_bundle.model_copy(
            update={"query_variants": variants, "metadata_filter": metadata_filter}
        )
        requested_top_k = min(
            top_k or self._settings.rag_final_parent_k,
            self._settings.rag_final_parent_k,
        )
        cache_status: CacheStatus = "disabled"
        cache_key: str | None = None
        should_cache = (
            mode == "hybrid_reranked"
            and use_cache
            and self._settings.rag_enable_cache
            and self._cache is not None
        )
        cache = self._cache
        if should_cache and cache is not None:
            cache_key = build_retrieval_cache_key(
                settings=self._settings,
                corpus_fingerprint=self._corpus_fingerprint,
                query_bundle=expanded_bundle,
            )
            lookup = await cache.get(cache_key)
            cache_status = lookup.status
            if lookup.result is not None:
                return lookup.result.model_copy(
                    update={
                        "contexts": lookup.result.contexts[:requested_top_k],
                        "parent_ids": lookup.result.parent_ids[:requested_top_k],
                    }
                )

        rankings: list[Sequence[RetrievalCandidate]] = []
        dense_rankings: list[list[RetrievalCandidate]] = []
        sparse_rankings: list[list[RetrievalCandidate]] = []
        degraded: list[str] = []
        fallback_used = False
        run_dense = mode in {"dense_only", "hybrid_rrf", "hybrid_reranked"}
        run_sparse = mode in {"bm25_only", "hybrid_rrf", "hybrid_reranked"}
        if run_dense:
            try:
                for variant in variants:
                    candidates, used = await asyncio.to_thread(
                        self._dense_store.search,
                        variant,
                        query_variant=variant,
                        top_k=self._settings.rag_dense_top_k,
                        city=query_bundle.destination,
                    )
                    dense_rankings.append(candidates)
                    fallback_used = fallback_used or used
            except Exception:
                dense_rankings = []
                degraded.append("dense")
        if run_sparse:
            try:
                sparse_rankings = [
                    self._sparse_index.search(
                        variant,
                        query_variant=variant,
                        top_k=self._settings.rag_sparse_top_k,
                        city=query_bundle.destination,
                    )
                    for variant in variants
                ]
            except Exception:
                sparse_rankings = []
                degraded.append("sparse")
        rankings = [*dense_rankings, *sparse_rankings]
        dense_count = sum(len(ranking) for ranking in dense_rankings)
        sparse_count = sum(len(ranking) for ranking in sparse_rankings)
        if not rankings or (dense_count == 0 and sparse_count == 0):
            return self._empty_result(
                expanded_bundle,
                cache_status=cache_status,
                degraded_components=sorted({*degraded, "retrieval"}),
                fallback_used=fallback_used,
                error="retrieval_unavailable",
            )

        fused = reciprocal_rank_fusion(
            rankings,
            rrf_k=self._settings.rag_rrf_k,
            top_k=self._settings.rag_fusion_top_k,
        )
        evidence = _best_child_by_parent(fused)
        parents: list[ParentDocument] = []
        for parent_id in evidence:
            parent = await self._parent_store.get(parent_id)
            if parent is not None:
                parents.append(parent)
        missing_parent_count = len(evidence) - len(parents)
        ranked: list[RerankedParent]
        if mode == "hybrid_reranked":
            try:
                ranked = await self._reranker.rerank(
                    parents=parents,
                    evidence=evidence,
                    query_bundle=expanded_bundle,
                    top_k=self._settings.rag_rerank_top_k,
                )
            except Exception:
                degraded.append("reranker")
                ranked = _rrf_parent_fallback(parents, evidence)
        else:
            ranked = _rrf_parent_fallback(parents, evidence)
        final = ranked[:requested_top_k]
        diagnostics = RetrievalDiagnostics(
            pipeline_version=self._settings.rag_pipeline_version,
            corpus_fingerprint=self._corpus_fingerprint,
            embedding_backend=self._settings.rag_embedding_backend,
            embedding_model=self._settings.rag_embedding_model,
            query_variant_count=len(variants),
            dense_candidate_count=dense_count,
            sparse_candidate_count=sparse_count,
            fused_candidate_count=len(fused),
            reranked_candidate_count=len(ranked),
            returned_parent_count=len(final),
            metadata_filter_applied=bool(metadata_filter),
            metadata_filter_fallback_used=fallback_used,
            cache_status=cache_status,
            degraded_components=sorted(set(degraded)),
            missing_parent_count=missing_parent_count,
        )
        result = AdvancedRetrievalResult(
            contexts=[_format_parent_context(parent) for parent in final],
            parent_ids=[parent.parent_id for parent in final],
            query_variants=variants,
            diagnostics=diagnostics,
        )
        if should_cache and cache_key is not None and self._cache is not None:
            if not await self._cache.set(cache_key, result):
                diagnostics = diagnostics.model_copy(update={"cache_status": "unavailable"})
                result = result.model_copy(update={"diagnostics": diagnostics})
        return result

    def _empty_result(
        self,
        query_bundle: QueryBundle,
        *,
        cache_status: CacheStatus,
        degraded_components: list[str],
        fallback_used: bool,
        error: str,
    ) -> AdvancedRetrievalResult:
        """Return a safe no-context result without exception details."""

        return AdvancedRetrievalResult(
            contexts=[],
            parent_ids=[],
            query_variants=query_bundle.query_variants,
            diagnostics=RetrievalDiagnostics(
                pipeline_version=self._settings.rag_pipeline_version,
                corpus_fingerprint=self._corpus_fingerprint,
                embedding_backend=self._settings.rag_embedding_backend,
                embedding_model=self._settings.rag_embedding_model,
                query_variant_count=len(query_bundle.query_variants),
                dense_candidate_count=0,
                sparse_candidate_count=0,
                fused_candidate_count=0,
                reranked_candidate_count=0,
                returned_parent_count=0,
                metadata_filter_applied=bool(query_bundle.metadata_filter),
                metadata_filter_fallback_used=fallback_used,
                cache_status=cache_status,
                degraded_components=degraded_components,
            ),
            error=error,
        )


def _best_child_by_parent(candidates: Sequence[FusedCandidate]) -> dict[str, FusedCandidate]:
    """Keep one strongest child evidence item per parent in stable order."""

    best: dict[str, FusedCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (-item.rrf_score, item.child_id)):
        best.setdefault(candidate.parent_id, candidate)
    return best


def _rrf_parent_fallback(
    parents: Sequence[ParentDocument],
    evidence: Mapping[str, FusedCandidate],
) -> list[RerankedParent]:
    """Preserve fused parent order when the second-stage reranker is unavailable."""

    ranked = [
        RerankedParent(
            parent_id=parent.parent_id,
            source=parent.source,
            city=parent.city,
            title=parent.title,
            content=parent.content,
            rrf_score=evidence[parent.parent_id].rrf_score,
            rerank_score=evidence[parent.parent_id].rrf_score,
        )
        for parent in parents
        if parent.parent_id in evidence
    ]
    ranked.sort(key=lambda item: (-item.rrf_score, item.parent_id))
    return ranked


def _format_parent_context(parent: RerankedParent) -> str:
    """Attach safe source/title/city metadata to complete parent text."""

    return f"# {parent.title}\nSource: {parent.source} | City: {parent.city}\n\n{parent.content}"
