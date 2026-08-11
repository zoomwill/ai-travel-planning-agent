"""Retriever Agent node for deterministic local travel knowledge."""

from collections.abc import Callable

from app.graphs.state import TravelPlanState
from app.rag.retriever import retrieve_travel_context

ContextRetriever = Callable[[str], list[str]]


def retriever_node(
    state: TravelPlanState,
    *,
    context_retriever: ContextRetriever = retrieve_travel_context,
) -> TravelPlanState:
    """Retrieve context after routing and write it into shared graph state."""

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
        query_parts = [user_request]
        requirements = state.get("requirements")
        if requirements is not None and requirements.preferences:
            query_parts.append("Current trip preferences: " + ", ".join(requirements.preferences))
        remembered_preferences = state.get("remembered_preferences", [])
        if remembered_preferences:
            query_parts.append("Remembered preferences: " + ", ".join(remembered_preferences))
        retrieved_context = context_retriever("\n".join(query_parts))
    except Exception:
        return {
            "retrieved_context": [],
            "error": "Travel knowledge retrieval failed.",
        }

    return {
        "retrieved_context": retrieved_context,
        "error": None,
    }
