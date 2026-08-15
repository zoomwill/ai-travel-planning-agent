"""Tests for transparent deterministic parent feature reranking."""

import pytest

from app.rag.models import FusedCandidate, QueryBundle
from app.rag.reranker import DeterministicFeatureReranker
from tests.rag.helpers import make_parent


def evidence(parent_id: str, child: str, score: float) -> FusedCandidate:
    """Build one best-child evidence record for a parent."""

    return FusedCandidate(
        child_id=child * 64,
        parent_id=parent_id,
        rrf_score=score,
        dense_ranks=[1],
        matched_variants=["query"],
        retrieval_sources=["dense:query"],
    )


@pytest.mark.asyncio
async def test_city_and_preference_match_can_change_rrf_order() -> None:
    """Reranking uses content and city features rather than parent ID alone."""

    paris = make_parent(
        "a",
        city="Paris",
        content="General museum overview.",
    )
    tokyo = make_parent(
        "z",
        city="Tokyo",
        content="Tokyo quiet street photography neighborhoods avoid crowds.",
    )
    query = QueryBundle(
        original_query="Tokyo quiet street photography",
        destination="Tokyo",
        current_preferences=["photography"],
        remembered_preferences=["avoid crowds"],
    )
    reranker = DeterministicFeatureReranker()

    results = await reranker.rerank(
        parents=[paris, tokyo],
        evidence={
            paris.parent_id: evidence(paris.parent_id, "b", 0.20),
            tokyo.parent_id: evidence(tokyo.parent_id, "y", 0.19),
        },
        query_bundle=query,
        top_k=2,
    )

    assert results[0].parent_id == tokyo.parent_id
    assert results[0].matched_preferences == ["avoid crowds", "photography"]
    repeated = await reranker.rerank(
        parents=[paris, tokyo],
        evidence={
            paris.parent_id: evidence(paris.parent_id, "b", 0.20),
            tokyo.parent_id: evidence(tokyo.parent_id, "y", 0.19),
        },
        query_bundle=query,
        top_k=2,
    )
    assert results == repeated
