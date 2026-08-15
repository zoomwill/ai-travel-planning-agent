"""Explicitly download or load the configured Sentence Transformer model."""

import sys

from app.core.config import Settings
from app.rag.embeddings import SentenceTransformerEmbeddingBackend


def main() -> int:
    """Prepare one model without connecting to Chroma or Redis."""

    settings = Settings()
    try:
        embedding = SentenceTransformerEmbeddingBackend.load(
            settings.rag_embedding_model,
            device=settings.rag_embedding_device,
            normalize_embeddings=settings.rag_embedding_normalize,
            local_files_only=False,
        )
    except Exception as exc:
        print(f"FAIL model preparation: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"PASS model: {settings.rag_embedding_model}")
    print(f"PASS embedding dimension: {embedding.dimensions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
