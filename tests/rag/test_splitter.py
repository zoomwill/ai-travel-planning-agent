"""Tests for deterministic overlapping text chunks."""

import pytest
from langchain_core.documents import Document

from app.rag.splitter import split_documents


def test_splitter_is_deterministic_and_preserves_metadata() -> None:
    """The same text produces the same chunks, overlap, and IDs."""

    source = Document(
        page_content="abcdefghij",
        metadata={"source": "tokyo.md", "city": "Tokyo"},
    )

    first = split_documents([source], chunk_size=6, chunk_overlap=2)
    second = split_documents([source], chunk_size=6, chunk_overlap=2)

    assert first == second
    assert [chunk.page_content for chunk in first] == ["abcdef", "efghij"]
    assert [chunk.metadata for chunk in first] == [
        {"source": "tokyo.md", "city": "Tokyo", "chunk_id": "tokyo.md:0000"},
        {"source": "tokyo.md", "city": "Tokyo", "chunk_id": "tokyo.md:0001"},
    ]


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (10, -1), (10, 10), (10, 11)],
)
def test_splitter_rejects_non_progressing_settings(
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Invalid settings fail clearly instead of creating an infinite loop."""

    with pytest.raises(ValueError):
        split_documents([], chunk_size=chunk_size, chunk_overlap=chunk_overlap)
