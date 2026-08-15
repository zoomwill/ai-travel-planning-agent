"""Hand-calculated tests for rank-only Reciprocal Rank Fusion."""

import math

from app.rag.fusion import reciprocal_rank_fusion
from app.rag.models import RetrievalCandidate


def candidate(child: str, method: str, variant: str, rank: int) -> RetrievalCandidate:
    """Build one minimal valid ranking candidate."""

    return RetrievalCandidate(
        child_id=child * 64,
        parent_id=child.upper() * 64,
        source=f"{child}.md",
        city="Tokyo",
        content=child,
        retrieval_method=method,
        query_variant=variant,
        rank=rank,
        raw_score=999.0,
    )


def test_rrf_matches_formula_and_accumulates_multiple_rankings() -> None:
    """Raw retriever scores are irrelevant; only one-based ranks contribute."""

    dense = [candidate("a", "dense", "q1", 1), candidate("b", "dense", "q1", 2)]
    sparse = [candidate("b", "sparse", "q1", 1), candidate("a", "sparse", "q1", 2)]

    fused = reciprocal_rank_fusion([dense, sparse], rrf_k=60, top_k=2)

    expected = 1 / 61 + 1 / 62
    assert all(math.isclose(item.rrf_score, expected) for item in fused)
    assert [item.child_id for item in fused] == sorted(item.child_id for item in fused)


def test_rrf_is_independent_of_ranking_list_order() -> None:
    """Reordering independent dense/sparse lists does not change fused output."""

    first = [candidate("a", "dense", "q1", 1)]
    second = [candidate("a", "sparse", "q2", 2), candidate("b", "sparse", "q2", 1)]

    assert reciprocal_rank_fusion([first, second], rrf_k=60, top_k=5) == (
        reciprocal_rank_fusion([second, first], rrf_k=60, top_k=5)
    )
