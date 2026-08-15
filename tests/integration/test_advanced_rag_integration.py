"""Opt-in real-model checks against local Chroma and Redis P10 resources."""

import os

import chromadb
import pytest

from app.core.config import Settings
from app.infrastructure.redis import create_redis_client
from app.rag.cache import build_retrieval_cache_key
from app.rag.manifest import load_rag_manifest
from app.rag.models import QueryBundle
from app.rag.multi_query import DeterministicTravelQueryExpander
from app.rag.runtime import create_advanced_rag_runtime

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 after preparing the P10 model and index",
)
def test_real_index_preserves_old_collection_and_matches_manifest() -> None:
    """The separate child collection is exact while P06 knowledge still exists."""

    settings = Settings()
    manifest = load_rag_manifest(settings.rag_pipeline_version)
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
    )

    old_collection = client.get_collection("travel_knowledge")
    child_collection = client.get_collection(settings.rag_child_collection)

    assert old_collection.count() > 0
    assert child_collection.count() == manifest.metadata.child_count
    assert manifest.metadata.parent_count > 20
    assert manifest.metadata.child_count > 40


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 after preparing the P10 model and index",
)
@pytest.mark.asyncio
async def test_real_chinese_retrieval_cache_miss_hit_and_ttl() -> None:
    """One exact key proves cache-aside without touching unrelated Redis data."""

    settings = Settings()
    redis_client = create_redis_client(settings)
    bundle = QueryBundle(
        original_query="东京安静、适合街头摄影的社区",
        destination="Tokyo",
        current_preferences=["photography", "avoid crowds"],
    )
    expander = DeterministicTravelQueryExpander(variant_count=settings.rag_query_variant_count)
    variants = await expander.expand(bundle)
    expanded = bundle.model_copy(
        update={"query_variants": variants, "metadata_filter": {"city": "Tokyo"}}
    )
    manifest = load_rag_manifest(settings.rag_pipeline_version)
    cache_key = build_retrieval_cache_key(
        settings=settings,
        corpus_fingerprint=manifest.metadata.corpus_fingerprint,
        query_bundle=expanded,
    )
    try:
        await redis_client.delete(cache_key)
        runtime = await create_advanced_rag_runtime(settings, redis_client)
        assert runtime.indexed is True

        first = await runtime.retriever.retrieve(bundle)
        second = await runtime.retriever.retrieve(bundle)
        ttl = await redis_client.ttl(cache_key)

        assert first.error is None
        assert first.diagnostics.cache_status == "miss"
        assert second.diagnostics.cache_status == "hit"
        assert first.parent_ids == second.parent_ids
        assert len(first.parent_ids) == len(set(first.parent_ids))
        assert first.contexts
        assert all("City: Tokyo" in context for context in first.contexts)
        assert first.diagnostics.dense_candidate_count > 0
        assert first.diagnostics.sparse_candidate_count > 0
        assert 0 < ttl <= settings.rag_cache_ttl_seconds
    finally:
        await redis_client.delete(cache_key)
        await redis_client.aclose()
