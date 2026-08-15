"""Explicitly build and verify the versioned P10 advanced knowledge index."""

import asyncio
import sys

from app.core.config import Settings
from app.infrastructure.redis import create_redis_client
from app.rag.embeddings import SentenceTransformerEmbeddingBackend
from app.rag.indexer import index_advanced_corpus


async def index_once() -> bool:
    """Load the prepared model, index current fixtures, and close Redis cleanly."""

    settings = Settings()
    redis_client = create_redis_client(settings)
    try:
        embedding = SentenceTransformerEmbeddingBackend.load(
            settings.rag_embedding_model,
            device=settings.rag_embedding_device,
            normalize_embeddings=settings.rag_embedding_normalize,
            local_files_only=True,
        )
        stats = await index_advanced_corpus(
            settings,
            embedding_backend=embedding,
            redis_client=redis_client,
        )
    except Exception as exc:
        print(f"FAIL advanced indexing: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    finally:
        await redis_client.aclose()

    print(f"PASS Markdown documents: {stats.markdown_count}")
    print(f"PASS parent documents: {stats.parent_count}")
    print(f"PASS child chunks: {stats.child_count}")
    print(f"PASS embedding dimension: {stats.embedding_dimension}")
    print(f"PASS corpus fingerprint: {stats.corpus_fingerprint}")
    return True


def main() -> int:
    """Return nonzero when model loading, external writes, or verification fails."""

    return 0 if asyncio.run(index_once()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
