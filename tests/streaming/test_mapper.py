"""Whitelist mapping tests for real LangGraph v2 task/update shapes."""

from app.domain.models import QualityScore
from app.review.fingerprint import create_draft_fingerprint
from app.review.models import PlanReview, ReviewDecision, ReviewIssueCode
from app.streaming.mapper import LangGraphEventMapper
from app.streaming.models import StreamEventType
from tests.review.helpers import make_review_plan


def task_start(name: str, task_id: str, input_value: object) -> dict[str, object]:
    """Use the installed LangGraph 1.2.10 task-start shape."""

    return {
        "type": "tasks",
        "data": {"id": task_id, "name": name, "input": input_value, "triggers": []},
    }


def task_finish(
    name: str,
    task_id: str,
    result: object,
    error: object = None,
) -> dict[str, object]:
    """Use the installed LangGraph 1.2.10 task-finish shape."""

    return {
        "type": "tasks",
        "data": {
            "id": task_id,
            "name": name,
            "result": result,
            "error": error,
            "interrupts": [],
        },
    }


def test_known_node_mapping_and_unknown_node_are_safe() -> None:
    mapper = LangGraphEventMapper()

    started = mapper.map_chunk(task_start("retriever", "one", {"private_state": "secret"}))
    completed = mapper.map_chunk(task_finish("retriever", "one", {"raw": "secret"}))
    unknown = mapper.map_chunk(task_start("private.module.node", "two", {"dsn": "secret"}))

    assert started[0].event_type is StreamEventType.NODE_STARTED
    assert started[0].node == "advanced_retriever"
    assert started[0].data == {}
    assert completed[0].event_type is StreamEventType.NODE_COMPLETED
    assert completed[0].data == {}
    assert unknown == []
    assert "private" not in repr(started + completed)


def test_all_search_kinds_map_without_raw_task_or_provider_data() -> None:
    mapper = LangGraphEventMapper()
    kinds = ["flights", "hotels", "attractions", "weather", "route"]
    starts = []
    finishes = []
    for index, kind in enumerate(kinds):
        task_id = f"task-{index}"
        starts.extend(
            mapper.map_chunk(
                task_start(
                    "search_worker",
                    task_id,
                    {
                        "search_task": {"kind": kind, "request_fingerprint": "private"},
                        "requirements_data": {"password": "must-not-leak"},
                    },
                )
            )
        )
        finishes.extend(
            mapper.map_chunk(
                task_finish(
                    "search_worker",
                    task_id,
                    {
                        "search_results": [
                            {
                                "kind": kind,
                                "status": "ok",
                                "data": [{"provider_secret": "hidden"}] * (index + 1),
                            }
                        ]
                    },
                )
            )
        )

    assert [item.data["search_kind"] for item in starts] == kinds
    assert [item.data["search_kind"] for item in finishes] == kinds
    assert [item.data["result_count"] for item in finishes] == [1, 2, 3, 4, 5]
    assert {item.event_type for item in starts} == {StreamEventType.SEARCH_STARTED}
    assert {item.event_type for item in finishes} == {StreamEventType.SEARCH_COMPLETED}
    public = repr(starts + finishes)
    assert "request_fingerprint" not in public
    assert "provider_secret" not in public
    assert "password" not in public


def test_search_failure_uses_constant_safe_message() -> None:
    mapper = LangGraphEventMapper()
    mapper.map_chunk(
        task_start(
            "search_worker",
            "failed-task",
            {"search_task": {"kind": "flights"}},
        )
    )
    [failed] = mapper.map_chunk(
        task_finish(
            "search_worker",
            "failed-task",
            {
                "tool_errors": [
                    {
                        "kind": "flights",
                        "error_type": "provider_error",
                        "safe_message": "postgresql://secret traceback Bearer token",
                        "recoverable": True,
                    }
                ]
            },
        )
    )

    assert failed.event_type is StreamEventType.SEARCH_FAILED
    assert failed.data == {
        "search_kind": "flights",
        "error_code": "provider_error",
        "recoverable": True,
    }
    assert "postgresql" not in repr(failed)
    assert "Bearer" not in repr(failed)


def test_retrieval_update_exposes_only_whitelisted_diagnostics() -> None:
    mapper = LangGraphEventMapper()
    [event] = mapper.map_chunk(
        {
            "type": "updates",
            "data": {
                "retriever": {
                    "retrieved_context": ["private full document"],
                    "retrieval_parent_ids": ["parent-secret"],
                    "retrieval_query_variants": ["one", "two"],
                    "retrieval_diagnostics": {
                        "pipeline_version": "advanced-v1",
                        "corpus_fingerprint": "private-fingerprint",
                        "embedding_backend": "private-backend",
                        "embedding_model": "private-model",
                        "query_variant_count": 2,
                        "dense_candidate_count": 20,
                        "sparse_candidate_count": 20,
                        "fused_candidate_count": 8,
                        "reranked_candidate_count": 4,
                        "returned_parent_count": 1,
                        "metadata_filter_applied": True,
                        "metadata_filter_fallback_used": False,
                        "cache_status": "hit",
                        "degraded_components": [],
                        "missing_parent_count": 0,
                    },
                    "embedding": [0.1, 0.2],
                    "redis_key": "rag:private",
                }
            },
        }
    )

    assert event.event_type is StreamEventType.RETRIEVAL_COMPLETED
    assert event.data == {
        "returned_parent_count": 1,
        "query_variant_count": 2,
        "cache_status": "hit",
        "metadata_filter_applied": True,
        "metadata_filter_fallback_used": False,
    }
    assert "private" not in repr(event)
    assert "embedding" not in repr(event)
    assert "redis" not in repr(event)


def test_review_update_emits_actual_score_and_revision_only_for_revise() -> None:
    mapper = LangGraphEventMapper()
    plan = make_review_plan()
    review = PlanReview(
        review_round=1,
        draft_fingerprint=create_draft_fingerprint(plan),
        scores=QualityScore(
            completeness=90,
            feasibility=80,
            personalization=70,
            budget_fit=60,
            overall_score=75,
            critique="Apply the safe budget guidance.",
        ),
        decision=ReviewDecision.REVISE,
        issue_codes=[ReviewIssueCode.BUDGET_OVERRUN],
        critique="Apply the safe budget guidance.",
        suggested_changes=["Choose lower-cost existing options."],
    )

    events = mapper.map_chunk(
        {
            "type": "updates",
            "data": {
                "reviewer": {
                    "current_review": review.model_dump(mode="json"),
                    "review_status": "pending",
                    "finalization_reason": None,
                    "error": None,
                }
            },
        }
    )

    assert [event.event_type for event in events] == [
        StreamEventType.REVIEW_COMPLETED,
        StreamEventType.REVISION_STARTED,
    ]
    assert events[0].data["scores"]["overall_score"] == 75
    assert events[0].data["decision"] == "revise"
    assert events[1].data["review_round"] == 1


def test_forced_finalize_is_a_successful_review_without_revision() -> None:
    mapper = LangGraphEventMapper()
    plan = make_review_plan()
    review = PlanReview(
        review_round=3,
        draft_fingerprint=create_draft_fingerprint(plan),
        scores=QualityScore(
            completeness=80,
            feasibility=80,
            personalization=80,
            budget_fit=20,
            overall_score=65,
            critique="Maximum rounds reached.",
        ),
        decision=ReviewDecision.FORCED_FINALIZE,
        issue_codes=[ReviewIssueCode.BUDGET_OVERRUN],
        critique="Maximum rounds reached.",
        suggested_changes=["Verify the budget manually."],
    )

    events = mapper.map_chunk(
        {
            "type": "updates",
            "data": {
                "reviewer": {
                    "current_review": review.model_dump(mode="json"),
                    "review_status": "forced_finalized",
                    "finalization_reason": "max_review_rounds_reached",
                    "error": None,
                }
            },
        }
    )

    assert [event.event_type for event in events] == [StreamEventType.REVIEW_COMPLETED]
    assert events[0].data["review_status"] == "forced_finalized"
    assert events[0].data["finalization_reason"] == "max_review_rounds_reached"
