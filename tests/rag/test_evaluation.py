"""Pure offline tests for transparent parent-level retrieval metrics."""

import math

import pytest

from app.rag.evaluation import EvaluationQuery, evaluate_mode, metrics_at_k
from app.rag.models import AdvancedRetrievalResult, QueryBundle, RetrievalDiagnostics


def diagnostics() -> RetrievalDiagnostics:
    """Return minimal safe diagnostics for an evaluation double."""

    return RetrievalDiagnostics(
        pipeline_version="advanced-v1",
        corpus_fingerprint="f" * 64,
        embedding_backend="sentence_transformers",
        embedding_model="test-model",
        query_variant_count=1,
        dense_candidate_count=1,
        sparse_candidate_count=1,
        fused_candidate_count=1,
        reranked_candidate_count=1,
        returned_parent_count=1,
        metadata_filter_applied=True,
        metadata_filter_fallback_used=False,
        cache_status="disabled",
    )


def test_metrics_match_a_hand_calculated_parent_ranking() -> None:
    """P/R/MRR and graded NDCG use the documented formulas at K=4."""

    result = metrics_at_k(
        ["a", "b", "c", "c"],
        {"a": 3, "c": 1, "d": 2},
        k=4,
    )
    dcg = 7 / math.log2(2) + 1 / math.log2(4)
    ideal = 7 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)

    assert result.precision_at_k == 0.5
    assert result.recall_at_k == pytest.approx(2 / 3)
    assert result.mrr_at_k == 1
    assert result.ndcg_at_k == pytest.approx(dcg / ideal)


def test_metrics_handle_no_relevant_documents_and_reject_invalid_k() -> None:
    """An unlabeled query yields honest zeros rather than a divide-by-zero result."""

    assert metrics_at_k(["a"], {"a": 0}, k=4).model_dump() == {
        "precision_at_k": 0.0,
        "recall_at_k": 0.0,
        "mrr_at_k": 0.0,
        "ndcg_at_k": 0.0,
    }
    with pytest.raises(ValueError, match="greater than zero"):
        metrics_at_k([], {}, k=0)


@pytest.mark.asyncio
async def test_mode_evaluation_disables_cache_and_macro_averages() -> None:
    """The runner sends the requested mode and never evaluates a cached ranking."""

    class FakeRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []

        async def retrieve(
            self,
            query_bundle: QueryBundle,
            *,
            top_k: int | None = None,
            mode: str = "hybrid_reranked",
            use_cache: bool = True,
        ) -> AdvancedRetrievalResult:
            del top_k
            self.calls.append((query_bundle.original_query, mode, use_cache))
            return AdvancedRetrievalResult(
                contexts=["parent"],
                parent_ids=["a"],
                diagnostics=diagnostics(),
            )

    retriever = FakeRetriever()
    queries = [
        EvaluationQuery(
            query_id="q1",
            query="Tokyo",
            destination="Tokyo",
            relevance_judgments={"a": 3},
        ),
        EvaluationQuery(
            query_id="q2",
            query="Paris",
            destination="Paris",
            relevance_judgments={"b": 3},
        ),
    ]

    result = await evaluate_mode(  # type: ignore[arg-type]
        retriever,
        queries,
        mode="dense_only",
        k=4,
    )

    assert retriever.calls == [
        ("Tokyo", "dense_only", False),
        ("Paris", "dense_only", False),
    ]
    assert result.metrics.precision_at_k == pytest.approx(0.125)
    assert result.metrics.recall_at_k == pytest.approx(0.5)
    assert result.rankings == {"q1": ["a"], "q2": ["a"]}
