"""Tests for heading-aware P10 parent and child splitting."""

from langchain_core.documents import Document

from app.rag.parent_child import create_child_chunks, create_parent_documents


def source_document() -> Document:
    """Build two distinct Markdown sections with required metadata."""

    content = (
        "# Tokyo Demo\n\n## Quiet streets\n\n"
        + "Yanaka has narrow lanes. " * 18
        + "\n\n## Museums\n\n"
        + "Ueno groups several museums. " * 18
    )
    return Document(
        page_content=content,
        metadata={
            "source": "tokyo_demo.md",
            "city": "Tokyo",
            "document_type": "neighborhoods",
            "language": "en",
        },
    )


def test_markdown_headings_create_separate_stable_parents() -> None:
    """Content from one H2 section never leaks into the next parent."""

    first = create_parent_documents(
        [source_document()],
        index_version="advanced-v1",
        max_size=1200,
        overlap=150,
    )
    second = create_parent_documents(
        [source_document()],
        index_version="advanced-v1",
        max_size=1200,
        overlap=150,
    )

    assert first == second
    assert len(first) == 2
    assert "Yanaka" in first[0].content
    assert "Ueno" not in first[0].content
    assert "Ueno" in first[1].content
    assert first[0].section_path == ["Tokyo Demo", "Quiet streets"]


def test_children_stay_within_parent_and_retain_metadata() -> None:
    """Long parents create smaller repeatable chunks with parent IDs."""

    parents = create_parent_documents(
        [source_document()],
        index_version="advanced-v1",
        max_size=1200,
        overlap=150,
    )
    children = create_child_chunks(parents, max_size=180, overlap=30)
    repeated = create_child_chunks(parents, max_size=180, overlap=30)

    assert children == repeated
    assert len(children) >= 4
    assert {child.parent_id for child in children} == {parent.parent_id for parent in parents}
    for child in children:
        parent = next(parent for parent in parents if parent.parent_id == child.parent_id)
        assert child.content in parent.content
        assert child.city == "Tokyo"
