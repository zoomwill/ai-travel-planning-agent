"""Idempotent, non-destructive deployment prerequisites with no model/provider calls."""

import asyncio
from collections.abc import Iterable

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.infrastructure.redis import create_redis_client
from app.rag.advanced_vector_store import create_advanced_vector_store
from app.rag.embeddings import SentenceTransformerEmbeddingBackend
from app.rag.indexer import build_advanced_corpus
from app.rag.manifest import write_rag_manifest
from app.rag.parent_store import LocalManifestParentStore, RedisParentDocumentStore


def missing_ids(existing: Iterable[str], expected: Iterable[str]) -> set[str]:
    """Allow additions/retries only; incompatible indexes require a deliberate migration."""

    present, required = set(existing), set(expected)
    if present - required:
        raise ValueError("existing RAG index differs; manual migration review required")
    return required - present


async def bootstrap(settings: Settings) -> None:
    """Prepare persistence and the same P10 corpus, without clearing any data."""

    uri = settings.langgraph_postgres_uri.get_secret_value()
    async with await AsyncConnection.connect(uri, autocommit=True, connect_timeout=15) as lock:
        # Serialize overlapping deployments; this lock is released if the process exits.
        await lock.execute("SET statement_timeout = '120s'")
        await lock.execute("SELECT pg_advisory_lock(181710)")
        async with AsyncPostgresSaver.from_conn_string(
            uri, serde=create_strict_serializer()
        ) as saver:
            await saver.setup()
        async with AsyncPostgresStore.from_conn_string(uri) as store:
            await store.setup()
        embedding = await asyncio.to_thread(
            SentenceTransformerEmbeddingBackend.load,
            settings.rag_embedding_model,
            device=settings.rag_embedding_device,
            normalize_embeddings=settings.rag_embedding_normalize,
            local_files_only=True,
            revision=settings.rag_embedding_revision,
        )
        corpus = build_advanced_corpus(settings, embedding_dimension=embedding.dimensions)
        vector = await asyncio.to_thread(create_advanced_vector_store, settings, embedding)
        existing = await asyncio.to_thread(
            vector.existing_ids, index_version=settings.rag_pipeline_version
        )
        missing = missing_ids(existing, (child.child_id for child in corpus.children))
        if missing:
            await asyncio.to_thread(
                vector.upsert_children,
                [child for child in corpus.children if child.child_id in missing],
            )
        count = await asyncio.to_thread(vector.count)
        if count != len(corpus.children):
            raise ValueError("RAG collection count differs; manual review required")
        redis_client = create_redis_client(settings)
        try:
            parents = RedisParentDocumentStore.from_redis(
                redis_client,
                pipeline_version=settings.rag_pipeline_version,
                fallback=LocalManifestParentStore(list(corpus.parents)),
                operation_timeout_seconds=settings.infrastructure_timeout_seconds,
            )
            await parents.put_many(list(corpus.parents))
            write_rag_manifest(corpus.metadata, list(corpus.parents), list(corpus.children))
        finally:
            await redis_client.aclose()
    print("PASS deployment prerequisites: PostgreSQL schema and advanced RAG index ready")
