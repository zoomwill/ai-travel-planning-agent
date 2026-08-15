"""Small JSON-safe fixtures shared by P10 pure RAG tests."""

from app.rag.identity import sha256_text
from app.rag.models import ChildChunk, ParentDocument


def make_parent(
    suffix: str,
    *,
    city: str = "Tokyo",
    title: str = "Tokyo demo",
    content: str = "Yanaka offers quiet streets for photography.",
) -> ParentDocument:
    """Build one valid parent with a human-readable stable test ID."""

    return ParentDocument(
        parent_id=(suffix * 64)[:64],
        source=f"{city.casefold()}_{suffix}.md",
        city=city,
        document_type="neighborhoods",
        language="en",
        title=title,
        section_path=[title, "Places"],
        content=content,
        content_sha256=sha256_text(content),
        index_version="advanced-v1",
    )


def make_child(
    suffix: str,
    *,
    parent: ParentDocument | None = None,
    city: str = "Tokyo",
    content: str = "Yanaka quiet street photography",
) -> ChildChunk:
    """Build one valid child connected to an optional supplied parent."""

    resolved_parent = parent or make_parent(suffix, city=city, content=content)
    return ChildChunk(
        child_id=(suffix * 64)[:64],
        parent_id=resolved_parent.parent_id,
        source=resolved_parent.source,
        city=resolved_parent.city,
        document_type=resolved_parent.document_type,
        language=resolved_parent.language,
        chunk_index=0,
        content=content,
        content_sha256=sha256_text(content),
        index_version="advanced-v1",
    )
