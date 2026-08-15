"""Heading-aware parent and boundary-aware child splitting for P10."""

import re
from collections.abc import Iterable

from langchain_core.documents import Document

from app.rag.identity import canonical_sha256, sha256_text
from app.rag.models import ChildChunk, ParentDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CJK = re.compile(r"[\u3400-\u9fff]")


def create_parent_documents(
    documents: Iterable[Document],
    *,
    index_version: str,
    max_size: int,
    overlap: int,
) -> list[ParentDocument]:
    """Create stable parents from Markdown sections without crossing headings."""

    _validate_window(max_size, overlap)
    parents: list[ParentDocument] = []
    for document in documents:
        source = _metadata_text(document, "source")
        city = _metadata_text(document, "city")
        document_type = str(document.metadata.get("document_type") or "travel_guide")
        language = str(document.metadata.get("language") or _detect_language(document.page_content))
        title, sections = _markdown_sections(document.page_content)
        for section_path, section_content in sections:
            windows = _split_window(section_content, max_size=max_size, overlap=overlap)
            for window_index, content in enumerate(windows):
                path = [title, *section_path]
                if len(windows) > 1:
                    path.append(f"part-{window_index + 1}")
                content_hash = sha256_text(content)
                parent_id = canonical_sha256(
                    {
                        "city": city,
                        "content_sha256": content_hash,
                        "document_type": document_type,
                        "index_version": index_version,
                        "language": language,
                        "section_path": path,
                        "source": source,
                    }
                )
                parents.append(
                    ParentDocument(
                        parent_id=parent_id,
                        source=source,
                        city=city,
                        document_type=document_type,
                        language=language,
                        title=title,
                        section_path=path,
                        content=content,
                        content_sha256=content_hash,
                        index_version=index_version,
                    )
                )
    return parents


def create_child_chunks(
    parents: Iterable[ParentDocument],
    *,
    max_size: int,
    overlap: int,
) -> list[ChildChunk]:
    """Create deterministic small chunks that never cross a parent boundary."""

    _validate_window(max_size, overlap)
    children: list[ChildChunk] = []
    for parent in parents:
        for chunk_index, content in enumerate(
            _split_window(parent.content, max_size=max_size, overlap=overlap)
        ):
            content_hash = sha256_text(content)
            child_id = canonical_sha256(
                {
                    "chunk_index": chunk_index,
                    "content_sha256": content_hash,
                    "index_version": parent.index_version,
                    "parent_id": parent.parent_id,
                }
            )
            children.append(
                ChildChunk(
                    child_id=child_id,
                    parent_id=parent.parent_id,
                    source=parent.source,
                    city=parent.city,
                    document_type=parent.document_type,
                    language=parent.language,
                    chunk_index=chunk_index,
                    content=content,
                    content_sha256=content_hash,
                    index_version=parent.index_version,
                )
            )
    return sorted(children, key=lambda child: (child.parent_id, child.chunk_index, child.child_id))


def _markdown_sections(markdown: str) -> tuple[str, list[tuple[list[str], str]]]:
    """Parse one Markdown document into heading-scoped text sections."""

    document_title = "Untitled travel knowledge"
    heading_stack: list[str] = []
    current_path: list[str] = []
    current_lines: list[str] = []
    sections: list[tuple[list[str], str]] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((list(current_path) or [document_title], content))
        current_lines.clear()

    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match is None:
            current_lines.append(line)
            continue
        level = len(match.group(1))
        heading = match.group(2).strip()
        if level == 1:
            flush()
            document_title = heading
            heading_stack = [heading]
            current_path = []
            continue
        flush()
        heading_stack = heading_stack[: level - 1]
        while len(heading_stack) < level - 1:
            heading_stack.append(document_title)
        heading_stack.append(heading)
        current_path = [part for part in heading_stack[1:] if part != document_title]
        current_lines.append(line)
    flush()
    if not sections:
        stripped = markdown.strip()
        if stripped:
            sections.append(([document_title], stripped))
    return document_title, sections


def _split_window(text: str, *, max_size: int, overlap: int) -> list[str]:
    """Split near readable boundaries while retaining deterministic overlap."""

    if len(text) <= max_size:
        return [text.strip()]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_size, len(text))
        end = hard_end if hard_end == len(text) else _preferred_boundary(text, start, hard_end)
        if end <= start:
            end = hard_end
        content = text[start:end].strip()
        if content:
            chunks.append(content)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _preferred_boundary(text: str, start: int, hard_end: int) -> int:
    """Choose the latest paragraph, sentence, or whitespace boundary in a safe range."""

    minimum = start + max(1, (hard_end - start) // 2)
    for marker in ("\n\n", ". ", "。", "！", "？", " "):
        position = text.rfind(marker, minimum, hard_end)
        if position >= minimum:
            return position + len(marker)
    return hard_end


def _metadata_text(document: Document, key: str) -> str:
    """Read one required non-empty string metadata value."""

    value = document.metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"each document needs non-empty {key} metadata")
    return value.strip()


def _detect_language(content: str) -> str:
    """Use a transparent local fallback sufficient for demo fixture metadata."""

    return "zh" if _CJK.search(content) else "en"


def _validate_window(max_size: int, overlap: int) -> None:
    """Reject non-progressing parent or child window settings."""

    if max_size <= 0:
        raise ValueError("max_size must be greater than zero")
    if overlap < 0 or overlap >= max_size:
        raise ValueError("overlap must be non-negative and smaller than max_size")
