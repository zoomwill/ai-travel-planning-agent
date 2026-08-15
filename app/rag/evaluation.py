"""Transparent parent-level offline retrieval metrics and evaluation runner."""

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.rag.advanced_retriever import AdvancedRetriever
from app.rag.models import QueryBundle, RetrievalMode

DEFAULT_EVALUATION_DATASET: Final = (
    Path(__file__).resolve().parents[2] / "data" / "evaluation" / "rag_queries.json"
)


class EvaluationQuery(BaseModel):
    """One fixed human-labeled query with graded parent relevance."""

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    destination: str | None = None
    preferences: list[str] = Field(default_factory=list)
    relevance_judgments: dict[str, int] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RetrievalMetrics(BaseModel):
    """Four familiar metrics calculated at a fixed positive K."""

    precision_at_k: float = Field(ge=0, le=1)
    recall_at_k: float = Field(ge=0, le=1)
    mrr_at_k: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)


class ModeEvaluation(BaseModel):
    """Macro-average for one retrieval mode plus per-query rankings."""

    mode: RetrievalMode
    k: int = Field(gt=0)
    query_count: int = Field(ge=0)
    metrics: RetrievalMetrics
    rankings: dict[str, list[str]]


def load_evaluation_queries(
    path: Path = DEFAULT_EVALUATION_DATASET,
) -> list[EvaluationQuery]:
    """Load a fixed JSON list and reject duplicate query identifiers."""

    queries = TypeAdapter(list[EvaluationQuery]).validate_json(path.read_text(encoding="utf-8"))
    query_ids = [query.query_id for query in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("evaluation query IDs must be unique")
    return queries


def metrics_at_k(
    retrieved_parent_ids: Sequence[str],
    relevance_judgments: Mapping[str, int],
    *,
    k: int,
) -> RetrievalMetrics:
    """Calculate binary P/R/MRR and graded NDCG with explicit zero handling.

    A judgment greater than zero is relevant. Precision uses K as its
    denominator. NDCG uses gain ``2**grade - 1`` and ``log2(rank + 1)``.
    """

    if k <= 0:
        raise ValueError("k must be greater than zero")
    ranking = _stable_unique(retrieved_parent_ids)[:k]
    relevant = {parent_id for parent_id, grade in relevance_judgments.items() if grade > 0}
    relevant_retrieved = [parent_id for parent_id in ranking if parent_id in relevant]
    precision = len(relevant_retrieved) / k
    recall = len(relevant_retrieved) / len(relevant) if relevant else 0.0
    reciprocal_rank = next(
        (1.0 / rank for rank, parent_id in enumerate(ranking, start=1) if parent_id in relevant),
        0.0,
    )
    gains = [max(0, relevance_judgments.get(parent_id, 0)) for parent_id in ranking]
    dcg = _discounted_cumulative_gain(gains)
    ideal_grades = sorted(
        (max(0, grade) for grade in relevance_judgments.values()),
        reverse=True,
    )[:k]
    ideal_dcg = _discounted_cumulative_gain(ideal_grades)
    ndcg = dcg / ideal_dcg if ideal_dcg > 0 else 0.0
    return RetrievalMetrics(
        precision_at_k=precision,
        recall_at_k=recall,
        mrr_at_k=reciprocal_rank,
        ndcg_at_k=ndcg,
    )


async def evaluate_mode(
    retriever: AdvancedRetriever,
    queries: Sequence[EvaluationQuery],
    *,
    mode: RetrievalMode,
    k: int,
) -> ModeEvaluation:
    """Run one mode without cache and macro-average the fixed query set."""

    per_query: list[RetrievalMetrics] = []
    rankings: dict[str, list[str]] = {}
    for query in queries:
        result = await retriever.retrieve(
            QueryBundle(
                original_query=query.query,
                destination=query.destination,
                current_preferences=query.preferences,
            ),
            top_k=k,
            mode=mode,
            use_cache=False,
        )
        if result.error is not None:
            raise RuntimeError(f"{mode} retrieval returned {result.error}")
        rankings[query.query_id] = result.parent_ids
        per_query.append(metrics_at_k(result.parent_ids, query.relevance_judgments, k=k))
    return ModeEvaluation(
        mode=mode,
        k=k,
        query_count=len(queries),
        metrics=_macro_average(per_query),
        rankings=rankings,
    )


def write_evaluation_json(path: Path, report: Mapping[str, object]) -> None:
    """Write stable UTF-8 JSON produced from actual evaluation results."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _discounted_cumulative_gain(grades: Sequence[int]) -> float:
    """Return graded DCG with rank positions starting at one."""

    return sum(
        (math.pow(2.0, grade) - 1.0) / math.log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


def _macro_average(metrics: Sequence[RetrievalMetrics]) -> RetrievalMetrics:
    """Average each metric equally across queries; empty input yields zeros."""

    if not metrics:
        return RetrievalMetrics(
            precision_at_k=0,
            recall_at_k=0,
            mrr_at_k=0,
            ndcg_at_k=0,
        )
    count = len(metrics)
    return RetrievalMetrics(
        precision_at_k=sum(item.precision_at_k for item in metrics) / count,
        recall_at_k=sum(item.recall_at_k for item in metrics) / count,
        mrr_at_k=sum(item.mrr_at_k for item in metrics) / count,
        ndcg_at_k=sum(item.ndcg_at_k for item in metrics) / count,
    )


def _stable_unique(values: Sequence[str]) -> list[str]:
    """Discard duplicate parent IDs while retaining the first rank."""

    return list(dict.fromkeys(values))
