"""Rank-only Reciprocal Rank Fusion for dense and sparse child candidates."""

from collections import defaultdict
from collections.abc import Sequence

from app.rag.models import FusedCandidate, RetrievalCandidate


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RetrievalCandidate]],
    *,
    rrf_k: int = 60,
    top_k: int,
) -> list[FusedCandidate]:
    """Fuse independent rankings with ``sum(1 / (rrf_k + rank))``."""

    if rrf_k <= 0 or top_k <= 0:
        raise ValueError("rrf_k and top_k must be greater than zero")
    grouped: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for ranking in rankings:
        seen_in_ranking: set[str] = set()
        for candidate in ranking:
            if candidate.child_id in seen_in_ranking:
                continue
            seen_in_ranking.add(candidate.child_id)
            grouped[candidate.child_id].append(candidate)

    fused: list[FusedCandidate] = []
    for child_id, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.retrieval_method,
                item.query_variant.casefold(),
                item.rank,
                item.child_id,
            ),
        )
        parent_ids = {candidate.parent_id for candidate in ordered}
        if len(parent_ids) != 1:
            raise ValueError("one child ID cannot refer to multiple parents")
        fused.append(
            FusedCandidate(
                child_id=child_id,
                parent_id=ordered[0].parent_id,
                rrf_score=sum(1.0 / (rrf_k + candidate.rank) for candidate in ordered),
                dense_ranks=sorted(
                    candidate.rank for candidate in ordered if candidate.retrieval_method == "dense"
                ),
                sparse_ranks=sorted(
                    candidate.rank
                    for candidate in ordered
                    if candidate.retrieval_method == "sparse"
                ),
                matched_variants=sorted(
                    {candidate.query_variant for candidate in ordered},
                    key=str.casefold,
                ),
                retrieval_sources=sorted(
                    {
                        f"{candidate.retrieval_method}:{candidate.query_variant}"
                        for candidate in ordered
                    },
                    key=str.casefold,
                ),
            )
        )
    fused.sort(key=lambda candidate: (-candidate.rrf_score, candidate.child_id))
    return fused[:top_k]
