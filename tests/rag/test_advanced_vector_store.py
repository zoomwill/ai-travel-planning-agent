"""Fake-Chroma tests for P10 explicit dense retrieval."""

from collections.abc import Mapping

from app.rag.advanced_vector_store import AdvancedChromaVectorStore


class FakeEmbedding:
    """Record queries and return one fixed vector."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.25, 0.75]


class FakeCollection:
    """Return one child and retain every query kwarg for inspection."""

    def __init__(self) -> None:
        self.query_calls: list[dict[str, object]] = []

    def count(self) -> int:
        return 1

    def query(self, **kwargs: object) -> Mapping[str, object]:
        self.query_calls.append(kwargs)
        return {
            "ids": [["c" * 64]],
            "documents": [["Tokyo quiet streets"]],
            "metadatas": [
                [
                    {
                        "parent_id": "p" * 64,
                        "source": "tokyo.md",
                        "city": "Tokyo",
                    }
                ]
            ],
            "distances": [[0.1]],
        }

    def get(self, **kwargs: object) -> Mapping[str, object]:
        return {"ids": []}

    def upsert(self, **kwargs: object) -> None:
        del kwargs

    def delete(self, **kwargs: object) -> None:
        del kwargs


def test_dense_retrieval_passes_query_embedding_and_validated_where() -> None:
    """The adapter, not a raw user dictionary, constructs Chroma's city filter."""

    embedding = FakeEmbedding()
    collection = FakeCollection()
    store = AdvancedChromaVectorStore(
        collection,
        embedding,
        metadata_filter_fallback=False,
    )

    results, fallback = store.search(
        "东京街头摄影",
        query_variant="东京街头摄影",
        top_k=4,
        city="Tokyo",
    )

    assert embedding.queries == ["东京街头摄影"]
    assert collection.query_calls[0]["query_embeddings"] == [[0.25, 0.75]]
    assert collection.query_calls[0]["where"] == {"city": "Tokyo"}
    assert results[0].child_id == "c" * 64
    assert results[0].rank == 1
    assert fallback is False
