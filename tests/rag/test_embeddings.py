"""Tests for the offline deterministic embedding model."""

import math

import pytest

from app.rag.embeddings import DeterministicHashEmbedding


def test_same_input_returns_the_same_vector() -> None:
    """Hash embeddings are reproducible across calls."""

    model = DeterministicHashEmbedding(dimensions=64)

    first = model.embed_query("Tokyo street photography")
    second = model.embed_query("Tokyo street photography")

    assert first == second
    assert len(first) == 64
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_document_and_query_methods_share_one_vector_space() -> None:
    """The same text has the same vector through either public method."""

    model = DeterministicHashEmbedding(dimensions=32)

    assert model.embed_documents(["Paris museums"])[0] == model.embed_query("Paris museums")
    assert model.embed_query("Paris museums") != model.embed_query("Tokyo gardens")


def test_invalid_embedding_dimensions_are_rejected() -> None:
    """A vector cannot have zero dimensions."""

    with pytest.raises(ValueError, match="dimensions must be greater than zero"):
        DeterministicHashEmbedding(dimensions=0)
