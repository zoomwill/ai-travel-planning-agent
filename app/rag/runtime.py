"""Create one application-lifespan P10 semantic retrieval runtime."""

import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.rag.advanced_retriever import AdvancedRetriever, AdvancedTravelRetriever
from app.rag.advanced_vector_store import create_advanced_vector_store
from app.rag.bm25 import BM25SparseIndex
from app.rag.cache import RedisRetrievalCache
from app.rag.embeddings import SentenceTransformerEmbeddingBackend
from app.rag.manifest import LoadedRagManifest, load_rag_manifest
from app.rag.models import (
    AdvancedRetrievalResult,
    QueryBundle,
    RetrievalDiagnostics,
    RetrievalMode,
)
from app.rag.multi_query import DeterministicTravelQueryExpander
from app.rag.parent_store import LocalManifestParentStore, RedisParentDocumentStore
from app.rag.reranker import DeterministicFeatureReranker


@dataclass(frozen=True, slots=True)
class AdvancedRagRuntime:
    """Safe status plus one optional ready advanced retriever."""

    pipeline_version: str
    indexed: bool
    collection_name: str
    child_count: int
    parent_count: int
    corpus_fingerprint: str
    embedding_model: str
    embedding_dimension: int
    bm25_ready: bool
    retriever: AdvancedRetriever


class UnavailableAdvancedRetriever:
    """Return a safe degraded result when explicit indexing is not ready."""

    def __init__(self, settings: Settings, *, reason: str = "rag_not_indexed") -> None:
        self._settings = settings
        self._reason = reason

    async def retrieve(
        self,
        query_bundle: QueryBundle,
        *,
        top_k: int | None = None,
        mode: RetrievalMode = "hybrid_reranked",
        use_cache: bool = True,
    ) -> AdvancedRetrievalResult:
        """Return no fabricated context and only a stable component reason."""

        del top_k, mode, use_cache
        return AdvancedRetrievalResult(
            contexts=[],
            parent_ids=[],
            query_variants=[],
            diagnostics=RetrievalDiagnostics(
                pipeline_version=self._settings.rag_pipeline_version,
                corpus_fingerprint="",
                embedding_backend=self._settings.rag_embedding_backend,
                embedding_model=self._settings.rag_embedding_model,
                query_variant_count=0,
                dense_candidate_count=0,
                sparse_candidate_count=0,
                fused_candidate_count=0,
                reranked_candidate_count=0,
                returned_parent_count=0,
                metadata_filter_applied=bool(query_bundle.destination),
                metadata_filter_fallback_used=False,
                cache_status="disabled",
                degraded_components=["index"],
            ),
            error=self._reason,
        )


async def create_advanced_rag_runtime(
    settings: Settings,
    redis_client: Redis,
) -> AdvancedRagRuntime:
    """Load a prepared local model and manifest once without downloading or indexing."""

    unavailable = UnavailableAdvancedRetriever(settings)
    try:
        manifest = await asyncio.to_thread(load_rag_manifest, settings.rag_pipeline_version)
        _validate_manifest_settings(settings, manifest)
        embedding = await asyncio.to_thread(
            SentenceTransformerEmbeddingBackend.load,
            settings.rag_embedding_model,
            device=settings.rag_embedding_device,
            normalize_embeddings=settings.rag_embedding_normalize,
            local_files_only=True,
            revision=settings.rag_embedding_revision,
        )
        if embedding.dimensions != manifest.metadata.embedding_dimension:
            raise ValueError("prepared model dimension does not match manifest")
        dense_store = await asyncio.to_thread(create_advanced_vector_store, settings, embedding)
        child_count = await asyncio.to_thread(dense_store.count)
        if child_count != manifest.metadata.child_count:
            raise ValueError("Chroma child count does not match local manifest")
        sparse_index = BM25SparseIndex(manifest.children)
        local_parents = LocalManifestParentStore(list(manifest.parents))
        parent_store = RedisParentDocumentStore.from_redis(
            redis_client,
            pipeline_version=settings.rag_pipeline_version,
            fallback=local_parents,
            operation_timeout_seconds=settings.infrastructure_timeout_seconds,
        )
        cache = RedisRetrievalCache.from_redis(
            redis_client,
            ttl_seconds=settings.rag_cache_ttl_seconds,
            operation_timeout_seconds=settings.infrastructure_timeout_seconds,
        )
        retriever = AdvancedTravelRetriever(
            settings=settings,
            corpus_fingerprint=manifest.metadata.corpus_fingerprint,
            query_expander=DeterministicTravelQueryExpander(
                variant_count=settings.rag_query_variant_count
            ),
            dense_store=dense_store,
            sparse_index=sparse_index,
            parent_store=parent_store,
            reranker=DeterministicFeatureReranker(),
            cache=cache,
        )
    except Exception:
        return _unavailable_runtime(settings, unavailable)
    return AdvancedRagRuntime(
        pipeline_version=settings.rag_pipeline_version,
        indexed=True,
        collection_name=settings.rag_child_collection,
        child_count=child_count,
        parent_count=manifest.metadata.parent_count,
        corpus_fingerprint=manifest.metadata.corpus_fingerprint,
        embedding_model=settings.rag_embedding_model,
        embedding_dimension=embedding.dimensions,
        bm25_ready=True,
        retriever=retriever,
    )


def _validate_manifest_settings(settings: Settings, manifest: LoadedRagManifest) -> None:
    """Reject a manifest built for another collection, model, or pipeline version."""

    metadata = manifest.metadata
    if metadata.pipeline_version != settings.rag_pipeline_version:
        raise ValueError("manifest pipeline version does not match settings")
    if metadata.collection_name != settings.rag_child_collection:
        raise ValueError("manifest collection does not match settings")
    if metadata.embedding_model != settings.rag_embedding_model:
        raise ValueError("manifest embedding model does not match settings")


def _unavailable_runtime(
    settings: Settings,
    retriever: AdvancedRetriever,
) -> AdvancedRagRuntime:
    """Build an inspectable not-indexed runtime without internal exception details."""

    return AdvancedRagRuntime(
        pipeline_version=settings.rag_pipeline_version,
        indexed=False,
        collection_name=settings.rag_child_collection,
        child_count=0,
        parent_count=0,
        corpus_fingerprint="",
        embedding_model=settings.rag_embedding_model,
        embedding_dimension=0,
        bm25_ready=False,
        retriever=retriever,
    )
