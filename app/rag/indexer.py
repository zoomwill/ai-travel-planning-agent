"""Explicit, idempotent construction of the versioned P10 local index."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.rag.advanced_vector_store import create_advanced_vector_store
from app.rag.embeddings import SentenceTransformerEmbeddingBackend
from app.rag.identity import corpus_fingerprint
from app.rag.loader import load_advanced_markdown_documents
from app.rag.manifest import load_rag_manifest, write_rag_manifest
from app.rag.models import ChildChunk, ParentDocument, RagIndexManifest
from app.rag.parent_child import create_child_chunks, create_parent_documents
from app.rag.parent_store import LocalManifestParentStore, RedisParentDocumentStore


@dataclass(frozen=True, slots=True)
class AdvancedCorpus:
    """Fully deterministic parent/child input prepared before external writes."""

    metadata: RagIndexManifest
    parents: tuple[ParentDocument, ...]
    children: tuple[ChildChunk, ...]
    markdown_count: int


@dataclass(frozen=True, slots=True)
class AdvancedIndexStats:
    """Non-secret facts printed after one verified indexing run."""

    markdown_count: int
    parent_count: int
    child_count: int
    stale_child_count: int
    stale_parent_count: int
    corpus_fingerprint: str
    embedding_dimension: int


def build_advanced_corpus(
    settings: Settings,
    *,
    embedding_dimension: int,
) -> AdvancedCorpus:
    """Load fixtures and create stable parent, child, and fingerprint data."""

    documents = load_advanced_markdown_documents()
    parents = create_parent_documents(
        documents,
        index_version=settings.rag_pipeline_version,
        max_size=settings.rag_parent_chunk_size,
        overlap=settings.rag_parent_chunk_overlap,
    )
    children = create_child_chunks(
        parents,
        max_size=settings.rag_child_chunk_size,
        overlap=settings.rag_child_chunk_overlap,
    )
    fingerprint = corpus_fingerprint(
        parent_ids=[parent.parent_id for parent in parents],
        child_ids=[child.child_id for child in children],
        pipeline_version=settings.rag_pipeline_version,
        embedding_model=settings.rag_embedding_model,
    )
    metadata = RagIndexManifest(
        pipeline_version=settings.rag_pipeline_version,
        collection_name=settings.rag_child_collection,
        corpus_fingerprint=fingerprint,
        embedding_backend=settings.rag_embedding_backend,
        embedding_model=settings.rag_embedding_model,
        embedding_dimension=embedding_dimension,
        parent_count=len(parents),
        child_count=len(children),
    )
    return AdvancedCorpus(
        metadata=metadata,
        parents=tuple(parents),
        children=tuple(children),
        markdown_count=len(documents),
    )


async def index_advanced_corpus(
    settings: Settings,
    *,
    embedding_backend: SentenceTransformerEmbeddingBackend,
    redis_client: Redis,
) -> AdvancedIndexStats:
    """Upsert current records, precisely remove stale P10 IDs, and verify results."""

    corpus = build_advanced_corpus(
        settings,
        embedding_dimension=embedding_backend.dimensions,
    )
    previous_parent_ids = _previous_parent_ids(settings.rag_pipeline_version)
    current_parent_ids = {parent.parent_id for parent in corpus.parents}
    vector_store = create_advanced_vector_store(settings, embedding_backend)
    current_child_ids = {child.child_id for child in corpus.children}
    existing_child_ids = vector_store.existing_ids(index_version=settings.rag_pipeline_version)
    stale_child_ids = sorted(existing_child_ids - current_child_ids)
    stale_parent_ids = sorted(previous_parent_ids - current_parent_ids)

    print(f"INFO stale P10 child IDs scheduled for exact deletion: {len(stale_child_ids)}")
    print(f"INFO stale P10 parent keys scheduled for exact deletion: {len(stale_parent_ids)}")

    vector_store.upsert_children(corpus.children)
    vector_store.delete_ids(stale_child_ids)

    local_store = LocalManifestParentStore(list(corpus.parents))
    parent_store = RedisParentDocumentStore.from_redis(
        redis_client,
        pipeline_version=settings.rag_pipeline_version,
        fallback=local_store,
        operation_timeout_seconds=settings.infrastructure_timeout_seconds,
    )
    await parent_store.put_many(list(corpus.parents))
    if stale_parent_ids:
        await redis_client.delete(
            *[parent_store.key_for(parent_id) for parent_id in stale_parent_ids]
        )

    write_rag_manifest(corpus.metadata, list(corpus.parents), list(corpus.children))
    await _verify_index(
        corpus,
        settings=settings,
        vector_store=vector_store,
        redis_client=redis_client,
        parent_store=parent_store,
    )
    return AdvancedIndexStats(
        markdown_count=corpus.markdown_count,
        parent_count=len(corpus.parents),
        child_count=len(corpus.children),
        stale_child_count=len(stale_child_ids),
        stale_parent_count=len(stale_parent_ids),
        corpus_fingerprint=corpus.metadata.corpus_fingerprint,
        embedding_dimension=embedding_backend.dimensions,
    )


def _previous_parent_ids(pipeline_version: str) -> set[str]:
    """Read only the previous same-version manifest for exact stale cleanup."""

    try:
        previous = load_rag_manifest(pipeline_version)
    except (FileNotFoundError, ValueError):
        return set()
    return {parent.parent_id for parent in previous.parents}


async def _verify_index(
    corpus: AdvancedCorpus,
    *,
    settings: Settings,
    vector_store: object,
    redis_client: Redis,
    parent_store: RedisParentDocumentStore,
) -> None:
    """Verify exact child IDs, total count, Redis values, and local manifest."""

    from app.rag.advanced_vector_store import AdvancedChromaVectorStore

    if not isinstance(vector_store, AdvancedChromaVectorStore):
        raise TypeError("vector_store must be AdvancedChromaVectorStore")
    expected_child_ids = {child.child_id for child in corpus.children}
    actual_child_ids = vector_store.existing_ids(index_version=settings.rag_pipeline_version)
    if actual_child_ids != expected_child_ids:
        raise ValueError("Chroma P10 child IDs do not match the current manifest")
    if vector_store.count() != len(corpus.children):
        raise ValueError("Chroma collection count does not match the current manifest")

    for parent in corpus.parents:
        raw = await redis_client.get(parent_store.key_for(parent.parent_id))
        if raw is None or ParentDocument.model_validate_json(raw) != parent:
            raise ValueError("Redis parent records do not match the current manifest")

    loaded = load_rag_manifest(settings.rag_pipeline_version)
    if loaded.metadata != corpus.metadata:
        raise ValueError("local manifest metadata did not round-trip")
    if len(loaded.parents) != len(corpus.parents) or len(loaded.children) != len(corpus.children):
        raise ValueError("local manifest counts did not round-trip")
