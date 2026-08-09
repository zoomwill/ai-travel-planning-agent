"""Explicitly index local Markdown travel knowledge into Chroma."""

import sys

from app.core.config import get_settings
from app.rag.loader import load_markdown_documents
from app.rag.splitter import split_documents
from app.rag.vector_store import VectorStoreError, create_chroma_vector_store


def main() -> int:
    """Load, split, embed, and upsert local knowledge without deleting data."""

    try:
        documents = load_markdown_documents()
        chunks = split_documents(documents)
        vector_store = create_chroma_vector_store(get_settings())
        indexed_count = vector_store.index_documents(chunks)
    except (OSError, ValueError, VectorStoreError) as exc:
        print(f"FAIL knowledge indexing: {exc}", file=sys.stderr)
        return 1

    print(
        f"PASS indexed {indexed_count} chunks from {len(documents)} Markdown files "
        "into travel_knowledge"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
