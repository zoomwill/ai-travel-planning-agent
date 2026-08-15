"""Offline P10 Retriever node, Reviewer, and checkpoint-safety tests."""

import json

import pytest
from langgraph.types import Overwrite

from app.core.persistence import create_strict_serializer
from app.graphs.nodes.retriever import advanced_retriever_node
from app.rag.models import (
    AdvancedRetrievalResult,
    QueryBundle,
    RetrievalDiagnostics,
)
from app.review.models import ReviewIssueCode
from app.review.reviewer import DeterministicPlanReviewer
from tests.review.helpers import make_review_plan


def result() -> AdvancedRetrievalResult:
    """Return a complete parent-level result without vectors or clients."""

    diagnostics = RetrievalDiagnostics(
        pipeline_version="advanced-v1",
        corpus_fingerprint="f" * 64,
        embedding_backend="sentence_transformers",
        embedding_model="test-model",
        query_variant_count=2,
        dense_candidate_count=4,
        sparse_candidate_count=4,
        fused_candidate_count=3,
        reranked_candidate_count=2,
        returned_parent_count=1,
        metadata_filter_applied=True,
        metadata_filter_fallback_used=False,
        cache_status="miss",
    )
    return AdvancedRetrievalResult(
        contexts=["Source: tokyo.md\nTitle: Quiet Tokyo\n\nFull parent text."],
        parent_ids=["p1"],
        query_variants=["Tokyo photography", "Tokyo quiet streets"],
        diagnostics=diagnostics,
    )


@pytest.mark.asyncio
async def test_advanced_node_replaces_old_thread_retrieval_state() -> None:
    """A second request clears Tokyo fields before writing its current result."""

    class FakeRetriever:
        def __init__(self) -> None:
            self.bundle: QueryBundle | None = None

        async def retrieve(self, query_bundle: QueryBundle, **kwargs: object):
            del kwargs
            self.bundle = query_bundle
            return result()

    fake = FakeRetriever()
    update = await advanced_retriever_node(
        {
            "user_request": "Plan Paris photography",
            "next_agent": "planner",
            "remembered_preferences": ["avoid crowds"],
            "retrieved_context": ["old Tokyo context"],
            "retrieval_query_variants": ["old Tokyo query"],
            "retrieval_parent_ids": ["old-tokyo-parent"],
            "retrieval_diagnostics": None,
            "retrieval_error": "old-error",
            "error": None,
        },
        advanced_retriever=fake,  # type: ignore[arg-type]
    )

    assert update["retrieved_context"] == Overwrite(result().contexts)
    assert update["retrieval_query_variants"] == Overwrite(result().query_variants)
    assert update["retrieval_parent_ids"] == Overwrite(["p1"])
    assert fake.bundle is not None
    assert fake.bundle.remembered_preferences == ["avoid crowds"]


def test_retrieval_state_round_trips_without_embedding_or_client_objects() -> None:
    """Only JSON-safe summaries enter strict MessagePack checkpoints."""

    state = {
        "retrieved_context": result().contexts,
        "retrieval_query_variants": result().query_variants,
        "retrieval_parent_ids": result().parent_ids,
        "retrieval_diagnostics": result().diagnostics.model_dump(mode="json"),
        "retrieval_error": None,
    }
    serializer = create_strict_serializer()

    restored = serializer.loads_typed(serializer.dumps_typed(state))
    serialized = json.dumps(restored, sort_keys=True).casefold()

    assert restored == state
    assert "embedding" in serialized
    assert "embedding_backend" in serialized
    assert "embedding_model" in serialized
    assert "embedding_values" not in serialized
    assert "redis" not in serialized
    assert "chroma_client" not in serialized


@pytest.mark.asyncio
async def test_reviewer_marks_retrieval_unavailable_as_noncritical() -> None:
    """P09 keeps running but receives an explicit non-critical P10 failure signal."""

    plan = make_review_plan()
    review = await DeterministicPlanReviewer().review(
        draft=plan,
        requirements=plan.requirements,
        search_summary={},
        retrieved_context=[],
        retrieval_error="retrieval_unavailable",
        remembered_preferences=[],
        tool_errors=[],
        review_round=1,
        score_threshold=80,
        max_review_rounds=3,
    )

    assert review.scores.completeness == 90
    assert ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE in review.issue_codes
