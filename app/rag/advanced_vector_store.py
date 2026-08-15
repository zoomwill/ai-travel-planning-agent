"""Versioned Chroma child index and explicit dense retrieval for P10."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

import chromadb

from app.core.config import Settings
from app.rag.embeddings import EmbeddingBackend
from app.rag.models import ChildChunk, RetrievalCandidate


class AdvancedCollection(Protocol):
    """Installed Chroma collection methods used by the advanced adapter."""

    def count(self) -> int:
        """Return record count."""

    def query(self, **kwargs: object) -> Mapping[str, object]:
        """Run explicit dense nearest-neighbor search."""

    def get(self, **kwargs: object) -> Mapping[str, object]:
        """Fetch existing records or IDs."""

    def upsert(self, **kwargs: object) -> None:
        """Create or update child records by deterministic ID."""

    def delete(self, **kwargs: object) -> object:
        """Delete only explicitly supplied child IDs."""


class AdvancedChromaVectorStore:
    """Own one versioned cosine collection and one semantic embedding backend."""

    def __init__(
        self,
        collection: AdvancedCollection,
        embedding_backend: EmbeddingBackend,
        *,
        metadata_filter_fallback: bool,
    ) -> None:
        self._collection = collection
        self._embedding_backend = embedding_backend
        self._metadata_filter_fallback = metadata_filter_fallback

    @property
    def collection(self) -> AdvancedCollection:
        """Expose the narrow collection surface to the explicit indexer."""

        return self._collection

    def count(self) -> int:
        """Return current child count."""

        return self._collection.count()

    def upsert_children(self, children: Sequence[ChildChunk]) -> int:
        """Embed and upsert children without printing or returning embeddings."""

        if not children:
            return 0
        embeddings = self._embedding_backend.embed_documents([child.content for child in children])
        if len(embeddings) != len(children):
            raise ValueError("embedding backend returned the wrong number of child vectors")
        self._collection.upsert(
            ids=[child.child_id for child in children],
            embeddings=embeddings,
            documents=[child.content for child in children],
            metadatas=[_child_metadata(child) for child in children],
        )
        return len(children)

    def existing_ids(self, *, index_version: str) -> set[str]:
        """Read IDs from only this pipeline version for precise stale cleanup."""

        result = self._collection.get(
            where={"index_version": index_version},
            include=[],
        )
        ids = result.get("ids", [])
        return {str(item) for item in cast(Sequence[object], ids)}

    def delete_ids(self, child_ids: Sequence[str]) -> int:
        """Delete an explicit non-empty ID list and nothing else."""

        unique_ids = sorted(set(child_ids))
        if not unique_ids:
            return 0
        self._collection.delete(ids=unique_ids)
        return len(unique_ids)

    def search(
        self,
        query: str,
        *,
        query_variant: str,
        top_k: int,
        city: str | None,
    ) -> tuple[list[RetrievalCandidate], bool]:
        """Run filtered dense retrieval and one explicit fallback when configured."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        query_embedding = self._embedding_backend.embed_query(query)
        where = {"city": city} if city else None
        result = self._query(query_embedding, top_k=top_k, where=where)
        candidates = _dense_candidates(result, query_variant=query_variant)
        fallback_used = False
        if where is not None and len(candidates) < top_k and self._metadata_filter_fallback:
            fallback_used = True
            result = self._query(query_embedding, top_k=top_k, where=None)
            candidates = _dense_candidates(result, query_variant=query_variant)
        return candidates[:top_k], fallback_used

    def _query(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        where: dict[str, str] | None,
    ) -> Mapping[str, object]:
        """Pass only validated adapter-built metadata filters to Chroma."""

        kwargs: dict[str, object] = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, max(1, self._collection.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            kwargs["where"] = where
        return self._collection.query(**kwargs)


def create_advanced_vector_store(
    settings: Settings,
    embedding_backend: EmbeddingBackend,
) -> AdvancedChromaVectorStore:
    """Open or create the separate cosine child collection through Chroma 1.5.9."""

    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
    )
    collection = client.get_or_create_collection(
        name=settings.rag_child_collection,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={
            "description": "Versioned P10 semantic child chunks",
            "pipeline_version": settings.rag_pipeline_version,
        },
        embedding_function=None,
    )
    return AdvancedChromaVectorStore(
        cast(AdvancedCollection, collection),
        embedding_backend,
        metadata_filter_fallback=settings.rag_metadata_filter_fallback,
    )


def _child_metadata(child: ChildChunk) -> dict[str, str | int]:
    """Return primitive metadata supported by the installed local Chroma."""

    return {
        "parent_id": child.parent_id,
        "source": child.source,
        "city": child.city,
        "document_type": child.document_type,
        "language": child.language,
        "chunk_index": child.chunk_index,
        "index_version": child.index_version,
        "content_sha256": child.content_sha256,
    }


def _dense_candidates(
    result: Mapping[str, object],
    *,
    query_variant: str,
) -> list[RetrievalCandidate]:
    """Parse one-query Chroma results and stabilize distance ties by child ID."""

    ids_groups = cast(list[list[str]], result.get("ids") or [])
    document_groups = cast(list[list[str | None]], result.get("documents") or [])
    metadata_groups = cast(list[list[dict[str, Any] | None]], result.get("metadatas") or [])
    distance_groups = cast(list[list[float | None]], result.get("distances") or [])
    if not ids_groups:
        return []
    ids = ids_groups[0]
    documents = document_groups[0] if document_groups else []
    metadatas = metadata_groups[0] if metadata_groups else []
    distances = distance_groups[0] if distance_groups else []
    parsed: list[tuple[float, str, dict[str, Any], str]] = []
    for index, child_id in enumerate(ids):
        raw_metadata = metadatas[index] if index < len(metadatas) else None
        metadata = raw_metadata or {}
        raw_content = documents[index] if index < len(documents) else None
        content = raw_content or ""
        raw_distance = distances[index] if index < len(distances) else None
        distance = raw_distance if raw_distance is not None else 0.0
        parent_id = metadata.get("parent_id")
        source = metadata.get("source")
        city = metadata.get("city")
        if not all(isinstance(value, str) and value for value in (parent_id, source, city)):
            continue
        parsed.append((float(distance), child_id, metadata, content))
    parsed.sort(key=lambda item: (item[0], item[1]))
    return [
        RetrievalCandidate(
            child_id=child_id,
            parent_id=cast(str, metadata["parent_id"]),
            source=cast(str, metadata["source"]),
            city=cast(str, metadata["city"]),
            content=content,
            retrieval_method="dense",
            query_variant=query_variant,
            rank=rank,
            raw_score=-distance,
        )
        for rank, (distance, child_id, metadata, content) in enumerate(parsed, start=1)
    ]
