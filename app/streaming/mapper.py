"""Whitelist conversion from LangGraph v2 chunks to public event drafts."""

from collections.abc import Mapping

from pydantic import ValidationError

from app.domain.models import TravelPlan
from app.rag.models import RetrievalDiagnostics
from app.review.models import PlanReview, ReviewDecision
from app.search.models import JsonObject, SearchKind, SearchKindValue, search_kind_value
from app.streaming.models import StreamEventDraft, StreamEventStatus, StreamEventType

_NODE_NAMES: dict[str, str] = {
    "memory_context": "memory_context",
    "router": "router",
    "retriever": "advanced_retriever",
    "prepare_search_tasks": "search_preparation",
    "aggregate_search_results": "search_aggregation",
    "initialize_review_cycle": "review_cycle",
    "planner": "planner",
    "reviewer": "reviewer",
    "finalize_plan": "finalize_plan",
}
_SEARCH_ERROR_CODES = {"empty_result", "invalid_result", "provider_error"}
_RETRIEVAL_ERROR_CODES = {"retrieval_query_invalid", "retrieval_unavailable"}


class LangGraphEventMapper:
    """Track task identity internally while exposing only approved business data."""

    def __init__(self) -> None:
        self._search_kinds: dict[str, SearchKindValue] = {}
        self._started_task_ids: set[str] = set()
        self._finished_task_ids: set[str] = set()
        self.final_plan: TravelPlan | None = None
        self.current_review: PlanReview | None = None
        self.review_status: str | None = None
        self.finalization_reason: str | None = None
        self.state_error: str | None = None

    def map_chunk(self, chunk: object) -> list[StreamEventDraft]:
        """Map one public LangGraph v2 chunk without serializing raw content."""

        if not isinstance(chunk, Mapping):
            return []
        mode = chunk.get("type")
        data = chunk.get("data")
        if mode == "tasks" and isinstance(data, Mapping):
            return self._map_task(data)
        if mode == "updates" and isinstance(data, Mapping):
            return self._map_updates(data)
        return []

    def observe_final_state(self, values: object) -> None:
        """Read only final safe models from a checkpoint fallback."""

        if not isinstance(values, Mapping):
            return
        self._observe_common_update(values)
        plan_value = values.get("travel_plan")
        if plan_value is not None:
            try:
                self.final_plan = TravelPlan.model_validate(plan_value)
            except ValidationError:
                self.final_plan = None

    def _map_task(self, task_event: Mapping[object, object]) -> list[StreamEventDraft]:
        name = task_event.get("name")
        task_id = task_event.get("id")
        if not isinstance(name, str) or not isinstance(task_id, str):
            return []
        is_start = "input" in task_event
        is_finish = "result" in task_event or "error" in task_event
        if name == "search_worker":
            if is_start:
                return self._map_search_start(task_id, task_event.get("input"))
            if is_finish:
                return self._map_search_finish(task_id, task_event)
            return []

        public_name = _NODE_NAMES.get(name)
        if public_name is None:
            return []
        if is_start and task_id not in self._started_task_ids:
            self._started_task_ids.add(task_id)
            return [
                StreamEventDraft(
                    event_type=StreamEventType.NODE_STARTED,
                    node=public_name,
                    status=StreamEventStatus.STARTED,
                    message=f"{public_name} started.",
                )
            ]
        if is_finish and task_id not in self._finished_task_ids:
            self._finished_task_ids.add(task_id)
            failed = task_event.get("error") is not None
            return [
                StreamEventDraft(
                    event_type=StreamEventType.NODE_COMPLETED,
                    node=public_name,
                    status=(StreamEventStatus.FAILED if failed else StreamEventStatus.COMPLETED),
                    message=(
                        f"{public_name} failed safely." if failed else f"{public_name} completed."
                    ),
                )
            ]
        return []

    def _map_search_start(self, task_id: str, input_value: object) -> list[StreamEventDraft]:
        if task_id in self._started_task_ids or not isinstance(input_value, Mapping):
            return []
        task = input_value.get("search_task")
        if not isinstance(task, Mapping):
            return []
        kind = _validated_search_kind(task.get("kind"))
        if kind is None:
            return []
        self._started_task_ids.add(task_id)
        self._search_kinds[task_id] = kind
        return [
            StreamEventDraft(
                event_type=StreamEventType.SEARCH_STARTED,
                node="travel_search",
                status=StreamEventStatus.STARTED,
                message=f"{kind} search started.",
                data={"search_kind": kind},
            )
        ]

    def _map_search_finish(
        self,
        task_id: str,
        task_event: Mapping[object, object],
    ) -> list[StreamEventDraft]:
        if task_id in self._finished_task_ids:
            return []
        kind = self._search_kinds.get(task_id)
        if kind is None:
            return []
        self._finished_task_ids.add(task_id)
        if task_event.get("error") is not None:
            return [self._search_failed(kind, "provider_error", True)]

        result = task_event.get("result")
        if not isinstance(result, Mapping):
            return [self._search_failed(kind, "invalid_result", False)]
        tool_errors = result.get("tool_errors")
        if isinstance(tool_errors, list):
            for error in tool_errors:
                if not isinstance(error, Mapping) or error.get("kind") != kind:
                    continue
                error_type = error.get("error_type")
                error_code = (
                    str(error_type) if error_type in _SEARCH_ERROR_CODES else "provider_error"
                )
                recoverable = error.get("recoverable") is True
                return [self._search_failed(kind, error_code, recoverable)]

        search_results = result.get("search_results")
        if isinstance(search_results, list):
            for envelope in search_results:
                if not isinstance(envelope, Mapping) or envelope.get("kind") != kind:
                    continue
                data = envelope.get("data")
                if envelope.get("status") == "ok" and isinstance(data, list):
                    return [
                        StreamEventDraft(
                            event_type=StreamEventType.SEARCH_COMPLETED,
                            node="travel_search",
                            status=StreamEventStatus.COMPLETED,
                            message=f"{kind} search completed.",
                            data={
                                "search_kind": kind,
                                "status": "ok",
                                "result_count": len(data),
                            },
                        )
                    ]
        return [self._search_failed(kind, "invalid_result", False)]

    def _search_failed(
        self,
        kind: SearchKindValue,
        error_code: str,
        recoverable: bool,
    ) -> StreamEventDraft:
        """Return a constant safe search error without exception content."""

        return StreamEventDraft(
            event_type=StreamEventType.SEARCH_FAILED,
            node="travel_search",
            status=StreamEventStatus.FAILED,
            message=f"The {kind} search is unavailable.",
            data={
                "search_kind": kind,
                "error_code": error_code,
                "recoverable": recoverable,
            },
        )

    def _map_updates(self, updates: Mapping[object, object]) -> list[StreamEventDraft]:
        events: list[StreamEventDraft] = []
        for node_name, update in updates.items():
            if not isinstance(node_name, str) or not isinstance(update, Mapping):
                continue
            self._observe_common_update(update)
            if node_name == "retriever":
                events.append(self._retrieval_completed(update))
            elif node_name == "reviewer":
                events.extend(self._review_events(update))
            elif node_name == "finalize_plan":
                plan_value = update.get("travel_plan")
                if plan_value is not None:
                    try:
                        self.final_plan = TravelPlan.model_validate(plan_value)
                    except ValidationError:
                        self.final_plan = None
        return events

    def _observe_common_update(self, update: Mapping[object, object]) -> None:
        if "error" in update:
            error = update.get("error")
            self.state_error = error if isinstance(error, str) and error else None
        review_status = update.get("review_status")
        if isinstance(review_status, str) and review_status in {
            "pending",
            "accepted",
            "forced_finalized",
            "failed",
        }:
            self.review_status = review_status
        finalization_reason = update.get("finalization_reason")
        if isinstance(finalization_reason, str):
            self.finalization_reason = finalization_reason
        review_value = update.get("current_review")
        if review_value is not None:
            try:
                self.current_review = PlanReview.model_validate(review_value)
            except ValidationError:
                self.current_review = None

    def _retrieval_completed(self, update: Mapping[object, object]) -> StreamEventDraft:
        public_data: JsonObject = {}
        diagnostics_value = update.get("retrieval_diagnostics")
        try:
            diagnostics = (
                RetrievalDiagnostics.model_validate(diagnostics_value)
                if diagnostics_value is not None
                else None
            )
        except ValidationError:
            diagnostics = None
        if diagnostics is not None:
            public_data.update(
                {
                    "returned_parent_count": diagnostics.returned_parent_count,
                    "query_variant_count": diagnostics.query_variant_count,
                    "cache_status": diagnostics.cache_status,
                    "metadata_filter_applied": diagnostics.metadata_filter_applied,
                    "metadata_filter_fallback_used": (diagnostics.metadata_filter_fallback_used),
                }
            )
        else:
            variants = update.get("retrieval_query_variants")
            parent_ids = update.get("retrieval_parent_ids")
            if isinstance(variants, list):
                public_data["query_variant_count"] = len(variants)
            if isinstance(parent_ids, list):
                public_data["returned_parent_count"] = len(parent_ids)
        retrieval_error = update.get("retrieval_error")
        if isinstance(retrieval_error, str):
            public_data["error_code"] = (
                retrieval_error
                if retrieval_error in _RETRIEVAL_ERROR_CODES
                else "retrieval_unavailable"
            )
        return StreamEventDraft(
            event_type=StreamEventType.RETRIEVAL_COMPLETED,
            node="advanced_retriever",
            status=StreamEventStatus.COMPLETED,
            message="Travel knowledge retrieval completed.",
            data=public_data,
        )

    def _review_events(self, update: Mapping[object, object]) -> list[StreamEventDraft]:
        review_value = update.get("current_review")
        try:
            review = PlanReview.model_validate(review_value)
        except ValidationError:
            return []
        self.current_review = review
        data: JsonObject = {
            "review_round": review.review_round,
            "decision": review.decision.value,
            "scores": {
                "completeness": review.scores.completeness,
                "feasibility": review.scores.feasibility,
                "personalization": review.scores.personalization,
                "budget_fit": review.scores.budget_fit,
                "overall_score": review.scores.overall_score,
            },
            "issue_codes": [issue.value for issue in review.issue_codes],
            "critique": review.critique,
            "suggested_changes": list(review.suggested_changes),
        }
        if self.review_status is not None:
            data["review_status"] = self.review_status
        if self.finalization_reason is not None:
            data["finalization_reason"] = self.finalization_reason
        events = [
            StreamEventDraft(
                event_type=StreamEventType.REVIEW_COMPLETED,
                node="reviewer",
                status=StreamEventStatus.COMPLETED,
                message=f"Quality review round {review.review_round} completed.",
                data=data,
            )
        ]
        if review.decision is ReviewDecision.REVISE:
            events.append(
                StreamEventDraft(
                    event_type=StreamEventType.REVISION_STARTED,
                    node="planner",
                    status=StreamEventStatus.STARTED,
                    message=f"Plan revision after review round {review.review_round} started.",
                    data={
                        "review_round": review.review_round,
                        "issue_codes": [issue.value for issue in review.issue_codes],
                        "suggested_changes": list(review.suggested_changes),
                    },
                )
            )
        return events


def _validated_search_kind(value: object) -> SearchKindValue | None:
    """Narrow an untrusted task value to one of the five public kinds."""

    if not isinstance(value, str):
        return None
    try:
        return search_kind_value(SearchKind(value))
    except ValueError:
        return None
