"""Idempotent, non-destructive deployment prerequisites with no model/provider calls."""

import asyncio
import gc
from collections.abc import Iterable
from itertools import islice

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.deployment.diagnostics import bootstrap_stage
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
    """Release startup-only references before the application loads its runtime model."""

    # A completed inner coroutine cannot keep its vector/model/corpus locals alive.
    # Collect any library/model cycles once at this boundary, never per batch or request.
    await _prepare(settings)
    gc.collect()
    bootstrap_stage("memory_released")
    bootstrap_stage("complete")
    print(
        "PASS deployment prerequisites: PostgreSQL schema and advanced RAG index ready",
        flush=True,
    )


async def _prepare(settings: Settings) -> None:
    """Own all bootstrap-only objects and perform non-destructive, bounded remote writes."""

    uri = settings.langgraph_postgres_uri.get_secret_value()
    bootstrap_stage("postgres_start")
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
        bootstrap_stage("postgres_ready")
        bootstrap_stage("embedding_load_start")
        embedding = await asyncio.to_thread(
            SentenceTransformerEmbeddingBackend.load,
            settings.rag_embedding_model,
            device=settings.rag_embedding_device,
            normalize_embeddings=settings.rag_embedding_normalize,
            local_files_only=True,
            revision=settings.rag_embedding_revision,
            batch_size=settings.rag_bootstrap_batch_size,
        )
        bootstrap_stage("embedding_ready")
        corpus = build_advanced_corpus(settings, embedding_dimension=embedding.dimensions)
        expected = [child.child_id for child in corpus.children]
        if len(set(expected)) != len(expected):
            raise ValueError("duplicate RAG child IDs require review")
        bootstrap_stage("corpus_ready", children=len(expected))
        bootstrap_stage("chroma_connect_start")
        vector = await asyncio.to_thread(create_advanced_vector_store, settings, embedding)
        bootstrap_stage("chroma_connected")
        existing = await asyncio.to_thread(
            vector.existing_ids, index_version=settings.rag_pipeline_version
        )
        missing = missing_ids(existing, expected)
        batch_size = settings.rag_bootstrap_batch_size
        batch_count = (len(missing) + batch_size - 1) // batch_size
        bootstrap_stage("chroma_existing_ids_ready", children=len(missing), batches=batch_count)
        # Preserve corpus order; iterating the missing-ID set would make insertion order unstable.
        children = (child for child in corpus.children if child.child_id in missing)
        number = 0
        while True:
            batch = tuple(islice(children, batch_size))
            if not batch:
                break
            number += 1
            bootstrap_stage(
                "chroma_index_batch_start", batch=number, batches=batch_count, children=len(batch)
            )
            await asyncio.to_thread(
                vector.upsert_children,
                batch,
            )
            bootstrap_stage(
                "chroma_index_batch_complete",
                batch=number,
                batches=batch_count,
                children=len(batch),
            )
        count = await asyncio.to_thread(vector.count)
        if count != len(corpus.children):
            raise ValueError("RAG collection count differs; manual review required")
        bootstrap_stage("chroma_ready", children=count)
        bootstrap_stage("redis_start")
        redis_client = create_redis_client(settings)
        try:
            parents = RedisParentDocumentStore.from_redis(
                redis_client,
                pipeline_version=settings.rag_pipeline_version,
                fallback=LocalManifestParentStore(list(corpus.parents)),
                operation_timeout_seconds=settings.infrastructure_timeout_seconds,
            )
            await parents.put_many(list(corpus.parents))
            bootstrap_stage("redis_ready")
            write_rag_manifest(corpus.metadata, list(corpus.parents), list(corpus.children))
            bootstrap_stage("manifest_ready")
        finally:
            await redis_client.aclose()
