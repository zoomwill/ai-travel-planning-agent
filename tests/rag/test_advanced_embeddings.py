"""Offline tests for P10 fake and SentenceTransformer embedding adapters."""

import math

import numpy as np

from app.rag.embeddings import (
    DeterministicHashEmbeddingBackend,
    SentenceTransformerEmbeddingBackend,
)


class FakeSentenceTransformer:
    """Return inspectable normalized vectors without loading a real model."""

    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def get_embedding_dimension(self) -> int:
        return 3

    def encode_document(self, sentences: list[str], **kwargs: object) -> np.ndarray:
        assert kwargs["normalize_embeddings"] is True
        self.document_calls += 1
        return np.asarray([[1.0, 0.0, 0.0] for _ in sentences])

    def encode_query(self, sentences: str, **kwargs: object) -> np.ndarray:
        assert sentences
        assert kwargs["normalize_embeddings"] is True
        self.query_calls += 1
        return np.asarray([0.0, 1.0, 0.0])

    def encode(self, sentences: str | list[str], **kwargs: object) -> object:
        raise AssertionError(f"fallback should not receive {sentences} {kwargs}")


def test_hash_test_backend_is_stable_normalized_and_same_dimension() -> None:
    """The unit-test backend remains deterministic but is not production semantic proof."""

    backend = DeterministicHashEmbeddingBackend(dimensions=32)
    documents = backend.embed_documents(["Tokyo photography", "Paris museums"])
    query = backend.embed_query("Tokyo photography")

    assert documents[0] == query
    assert all(len(vector) == 32 for vector in [*documents, query])
    assert math.isclose(sum(value * value for value in query), 1.0)


def test_sentence_transformer_adapter_uses_query_and_document_methods() -> None:
    """The production boundary selects the public retrieval-specific model methods."""

    model = FakeSentenceTransformer()
    backend = SentenceTransformerEmbeddingBackend(model, normalize_embeddings=True)

    assert backend.embed_documents(["one", "two"]) == [
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
    ]
    assert backend.embed_query("query") == [0.0, 1.0, 0.0]
    assert backend.dimensions == 3
    assert model.document_calls == 1
    assert model.query_calls == 1
