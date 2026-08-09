"""Split travel knowledge into reproducible overlapping character chunks."""

from typing import Final

from langchain_core.documents import Document

DEFAULT_CHUNK_SIZE: Final = 600
DEFAULT_CHUNK_OVERLAP: Final = 100


def split_documents(
    documents: list[Document],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    """Return fixed-size chunks while retaining source, city, and chunk ID."""

    _validate_chunk_settings(chunk_size, chunk_overlap)
    chunks: list[Document] = []

    for document in documents:
        source = document.metadata.get("source")
        city = document.metadata.get("city")
        if not isinstance(source, str) or not isinstance(city, str):
            raise ValueError("each source document needs string source and city metadata")

        step = chunk_size - chunk_overlap
        for chunk_index, start in enumerate(range(0, len(document.page_content), step)):
            end = min(start + chunk_size, len(document.page_content))
            chunk_text = document.page_content[start:end].strip()
            if chunk_text:
                metadata = dict(document.metadata)
                metadata["source"] = source
                metadata["city"] = city
                metadata["chunk_id"] = f"{source}:{chunk_index:04d}"
                chunks.append(Document(page_content=chunk_text, metadata=metadata))
            if end == len(document.page_content):
                break

    return chunks


def _validate_chunk_settings(chunk_size: int, chunk_overlap: int) -> None:
    """Reject settings that could produce empty or non-progressing chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
