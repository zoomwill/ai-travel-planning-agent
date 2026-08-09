"""Tests for local Markdown knowledge loading."""

from pathlib import Path

import pytest

from app.rag.loader import load_markdown_document, load_markdown_documents


def test_load_markdown_document_preserves_source_and_city(tmp_path: Path) -> None:
    """Filename-derived metadata accompanies the exact local text."""

    path = tmp_path / "tokyo.md"
    path.write_text("# Tokyo\n\nYanaka suits street photography.\n", encoding="utf-8")

    document = load_markdown_document(path)

    assert document.page_content == "# Tokyo\n\nYanaka suits street photography."
    assert document.metadata == {"source": "tokyo.md", "city": "Tokyo"}


def test_load_markdown_documents_uses_stable_filename_order(tmp_path: Path) -> None:
    """Filesystem creation order cannot change indexing order."""

    (tmp_path / "tokyo.md").write_text("Tokyo knowledge", encoding="utf-8")
    (tmp_path / "paris.md").write_text("Paris knowledge", encoding="utf-8")

    documents = load_markdown_documents(tmp_path)

    assert [document.metadata["source"] for document in documents] == [
        "paris.md",
        "tokyo.md",
    ]


def test_empty_markdown_document_is_rejected(tmp_path: Path) -> None:
    """An empty source cannot silently create a useless vector."""

    path = tmp_path / "tokyo.md"
    path.write_text("  \n", encoding="utf-8")

    with pytest.raises(ValueError, match="knowledge file is empty"):
        load_markdown_document(path)
