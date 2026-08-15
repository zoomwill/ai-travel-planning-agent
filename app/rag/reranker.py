"""Transparent deterministic second-stage parent reranking for P10."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.rag.bm25 import tokenize_for_retrieval
from app.rag.models import FusedCandidate, ParentDocument, QueryBundle, RerankedParent

RRF_WEIGHT = 0.35
CITY_WEIGHT = 0.20
QUERY_COVERAGE_WEIGHT = 0.20
CURRENT_PREFERENCE_WEIGHT = 0.10
REMEMBERED_PREFERENCE_WEIGHT = 0.10
TITLE_WEIGHT = 0.05


class CandidateReranker(Protocol):
    """Replaceable async parent reranking boundary for a future model."""

    async def rerank(
        self,
        *,
        parents: Sequence[ParentDocument],
        evidence: Mapping[str, FusedCandidate],
        query_bundle: QueryBundle,
        top_k: int,
    ) -> list[RerankedParent]:
        """Return parent-level results in final relevance order."""


class DeterministicFeatureReranker:
    """Score parents with documented untrained lexical and metadata features."""

    async def rerank(
        self,
        *,
        parents: Sequence[ParentDocument],
        evidence: Mapping[str, FusedCandidate],
        query_bundle: QueryBundle,
        top_k: int,
    ) -> list[RerankedParent]:
        """Compute fixed-weight scores and stable parent-ID ties."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        max_rrf = max((item.rrf_score for item in evidence.values()), default=1.0)
        query_tokens = set(tokenize_for_retrieval(query_bundle.original_query))
        current_preferences = [
            preference for preference in query_bundle.current_preferences if preference.strip()
        ]
        remembered_preferences = [
            preference for preference in query_bundle.remembered_preferences if preference.strip()
        ]
        results: list[RerankedParent] = []
        for parent in parents:
            parent_evidence = evidence.get(parent.parent_id)
            if parent_evidence is None:
                continue
            content_tokens = set(tokenize_for_retrieval(parent.content))
            title_tokens = set(tokenize_for_retrieval(" ".join(parent.section_path)))
            matched_query = sorted(query_tokens & content_tokens)
            matched_current = _matched_preferences(current_preferences, content_tokens)
            matched_remembered = _matched_preferences(remembered_preferences, content_tokens)
            score = (
                RRF_WEIGHT * (parent_evidence.rrf_score / max_rrf)
                + CITY_WEIGHT * _city_match(parent.city, query_bundle.destination)
                + QUERY_COVERAGE_WEIGHT * _coverage(matched_query, query_tokens)
                + CURRENT_PREFERENCE_WEIGHT
                * _preference_coverage(matched_current, current_preferences)
                + REMEMBERED_PREFERENCE_WEIGHT
                * _preference_coverage(matched_remembered, remembered_preferences)
                + TITLE_WEIGHT * _coverage(sorted(query_tokens & title_tokens), query_tokens)
            )
            results.append(
                RerankedParent(
                    parent_id=parent.parent_id,
                    source=parent.source,
                    city=parent.city,
                    title=parent.title,
                    content=parent.content,
                    rrf_score=parent_evidence.rrf_score,
                    rerank_score=round(score, 8),
                    matched_preferences=sorted(
                        {*matched_current, *matched_remembered},
                        key=str.casefold,
                    ),
                    matched_query_terms=matched_query,
                )
            )
        results.sort(key=lambda parent: (-parent.rerank_score, parent.parent_id))
        return results[:top_k]


def _city_match(city: str, destination: str | None) -> float:
    """Return one only for a non-empty exact case-insensitive city match."""

    return float(destination is not None and city.casefold() == destination.casefold())


def _coverage(matched: Sequence[str], expected: set[str]) -> float:
    """Return transparent set coverage while treating empty expectations neutrally."""

    return len(set(matched)) / len(expected) if expected else 1.0


def _matched_preferences(preferences: Sequence[str], content_tokens: set[str]) -> list[str]:
    """Return preferences whose normalized tokens all occur in the parent."""

    return [
        preference
        for preference in preferences
        if (tokens := set(tokenize_for_retrieval(preference))) and tokens <= content_tokens
    ]


def _preference_coverage(matched: Sequence[str], expected: Sequence[str]) -> float:
    """Treat absent preferences as fully satisfied rather than an unfair zero."""

    return len(matched) / len(expected) if expected else 1.0
