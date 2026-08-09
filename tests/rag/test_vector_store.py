"""Tests for the Chroma vector-store adapter using an in-memory fake."""

from collections.abc import Mapping

from langchain_core.documents import Document

from app.rag.embeddings import DeterministicHashEmbedding
from app.rag.vector_store import (
    TRAVEL_KNOWLEDGE_COLLECTION,
    ChromaVectorStore,
    MetadataValue,
)


class FakeCollection:
    """Store vectors in memory while matching the adapter's Chroma surface."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[list[float], dict[str, MetadataValue], str]] = {}

    def count(self) -> int:
        """Return the number of unique deterministic IDs."""

        return len(self.records)

    def upsert(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, MetadataValue]],
        documents: list[str],
    ) -> None:
        """Create or replace records exactly like Chroma upsert semantics."""

        for record_id, embedding, metadata, document in zip(
            ids,
            embeddings,
            metadatas,
            documents,
            strict=True,
        ):
            self.records[record_id] = (embedding, metadata, document)

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str],
    ) -> Mapping[str, object]:
        """Rank stored records by dot-product similarity."""

        del include
        query = query_embeddings[0]
        ranked = sorted(
            self.records.items(),
            key=lambda item: (
                -sum(left * right for left, right in zip(query, item[1][0], strict=True))
            ),
        )[:n_results]
        return {
            "documents": [[record[1][2] for record in ranked]],
            "metadatas": [[record[1][1] for record in ranked]],
            "distances": [[0.0 for _ in ranked]],
        }


class FakeClient:
    """Return one persistent fake collection without any network call."""

    def __init__(self) -> None:
        self.collection = FakeCollection()
        self.collection_name: str | None = None

    def get_or_create_collection(
        self,
        *,
        name: str,
        metadata: dict[str, MetadataValue],
        embedding_function: None,
    ) -> FakeCollection:
        """Record collection configuration and preserve existing records."""

        del metadata, embedding_function
        self.collection_name = name
        return self.collection


def test_index_documents_uses_collection_and_deterministic_upsert_ids() -> None:
    """Repeated indexing updates records instead of duplicating them."""

    client = FakeClient()
    store = ChromaVectorStore(
        client,
        DeterministicHashEmbedding(dimensions=64),
        timeout_seconds=1,
    )
    documents = [
        Document(
            page_content="Tokyo Yanaka street photography",
            metadata={"source": "tokyo.md", "city": "Tokyo", "chunk_id": "tokyo.md:0000"},
        ),
        Document(
            page_content="Paris museum and garden walking",
            metadata={"source": "paris.md", "city": "Paris", "chunk_id": "paris.md:0000"},
        ),
    ]

    assert store.index_documents(documents) == 2
    assert store.index_documents(documents) == 2
    assert client.collection_name == TRAVEL_KNOWLEDGE_COLLECTION
    assert client.collection.count() == 2
    assert set(client.collection.records) == {"tokyo.md:0000", "paris.md:0000"}


def test_search_documents_returns_similar_content_and_metadata() -> None:
    """Query embeddings retrieve stored LangChain documents in similarity order."""

    client = FakeClient()
    store = ChromaVectorStore(
        client,
        DeterministicHashEmbedding(dimensions=64),
        timeout_seconds=1,
    )
    store.index_documents(
        [
            Document(
                page_content="Tokyo Yanaka street photography",
                metadata={
                    "source": "tokyo.md",
                    "city": "Tokyo",
                    "chunk_id": "tokyo.md:0000",
                },
            ),
            Document(
                page_content="Paris museum and garden walking",
                metadata={
                    "source": "paris.md",
                    "city": "Paris",
                    "chunk_id": "paris.md:0000",
                },
            ),
        ]
    )

    results = store.search_documents("Tokyo photography", top_k=1)

    assert [document.page_content for document in results] == ["Tokyo Yanaka street photography"]
    assert results[0].metadata["city"] == "Tokyo"
