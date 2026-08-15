"""Retriever Agent node for deterministic local travel knowledge."""

from collections.abc import Callable
from typing import Any

from langgraph.types import Overwrite

from app.graphs.state import TravelPlanState
from app.rag.advanced_retriever import AdvancedRetriever
from app.rag.models import QueryBundle
from app.rag.retriever import retrieve_travel_context
from app.search.models import dump_model_json

ContextRetriever = Callable[[str], list[str]]


def retriever_node(
    state: TravelPlanState,
    *,
    context_retriever: ContextRetriever = retrieve_travel_context,
) -> TravelPlanState:
    """Preserve the synchronous P06 node surface for backward compatibility."""

    if state.get("next_agent") != "planner":
        return {
            "retrieved_context": [],
            "error": state.get("error") or "The Retriever Agent was not selected.",
        }
    user_request = state.get("user_request", "").strip()
    if not user_request:
        return {
            "retrieved_context": [],
            "error": "A non-empty user request is required for retrieval.",
        }
    try:
        context = context_retriever(user_request)
    except Exception:
        return {
            "retrieved_context": [],
            "error": "Travel knowledge retrieval failed.",
        }
    return {"retrieved_context": context, "error": None}


async def advanced_retriever_node(
    state: TravelPlanState,
    *,
    context_retriever: ContextRetriever = retrieve_travel_context,
    advanced_retriever: AdvancedRetriever | None = None,
) -> dict[str, Any]:
    """Run P10 retrieval while resetting every persistence-safe retrieval field."""

    if state.get("next_agent") != "planner":
        return {
            "retrieved_context": _replace(state, "retrieved_context", []),
            "retrieval_query_variants": _replace(state, "retrieval_query_variants", []),
            "retrieval_parent_ids": _replace(state, "retrieval_parent_ids", []),
            "retrieval_diagnostics": _replace(state, "retrieval_diagnostics", None),
            "retrieval_error": _replace(state, "retrieval_error", None),
            "error": state.get("error") or "The Retriever Agent was not selected.",
        }

    user_request = state.get("user_request", "").strip()
    if not user_request:
        return {
            "retrieved_context": _replace(state, "retrieved_context", []),
            "retrieval_query_variants": _replace(state, "retrieval_query_variants", []),
            "retrieval_parent_ids": _replace(state, "retrieval_parent_ids", []),
            "retrieval_diagnostics": _replace(state, "retrieval_diagnostics", None),
            "retrieval_error": _replace(state, "retrieval_error", "retrieval_query_invalid"),
            "error": "A non-empty user request is required for retrieval.",
        }

    try:
        query_parts = [user_request]
        requirements = state.get("requirements")
        if requirements is not None and requirements.preferences:
            query_parts.append("Current trip preferences: " + ", ".join(requirements.preferences))
        remembered_preferences = state.get("remembered_preferences", [])
        if remembered_preferences:
            query_parts.append("Remembered preferences: " + ", ".join(remembered_preferences))
        combined_query = "\n".join(query_parts)
        if advanced_retriever is not None:
            requirements = state.get("requirements")
            result = await advanced_retriever.retrieve(
                QueryBundle(
                    original_query=combined_query,
                    destination=requirements.destination if requirements is not None else None,
                    current_preferences=(
                        list(requirements.preferences) if requirements is not None else []
                    ),
                    remembered_preferences=state.get("remembered_preferences", []),
                )
            )
            return {
                "retrieved_context": _replace(state, "retrieved_context", result.contexts),
                "retrieval_query_variants": _replace(
                    state,
                    "retrieval_query_variants",
                    result.query_variants,
                ),
                "retrieval_parent_ids": _replace(state, "retrieval_parent_ids", result.parent_ids),
                "retrieval_diagnostics": _replace(
                    state,
                    "retrieval_diagnostics",
                    dump_model_json(result.diagnostics),
                ),
                "retrieval_error": _replace(state, "retrieval_error", result.error),
                "error": None,
            }
        retrieved_context = context_retriever(combined_query)
    except Exception:
        return {
            "retrieved_context": _replace(state, "retrieved_context", []),
            "retrieval_query_variants": _replace(state, "retrieval_query_variants", []),
            "retrieval_parent_ids": _replace(state, "retrieval_parent_ids", []),
            "retrieval_diagnostics": _replace(state, "retrieval_diagnostics", None),
            "retrieval_error": _replace(state, "retrieval_error", "retrieval_unavailable"),
            "error": (
                None if advanced_retriever is not None else "Travel knowledge retrieval failed."
            ),
        }

    return {
        "retrieved_context": _replace(state, "retrieved_context", retrieved_context),
        "retrieval_query_variants": _replace(state, "retrieval_query_variants", [combined_query]),
        "retrieval_parent_ids": _replace(state, "retrieval_parent_ids", []),
        "retrieval_diagnostics": _replace(state, "retrieval_diagnostics", None),
        "retrieval_error": _replace(state, "retrieval_error", None),
        "error": None,
    }


def _replace(state: TravelPlanState, field: str, value: Any) -> Any:
    """Use Overwrite for persistent reused channels and raw values on first write."""

    return Overwrite(value) if field in state else value
