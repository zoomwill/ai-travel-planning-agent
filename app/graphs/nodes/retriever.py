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
        retrieved_context = context_retriever(user_request)
    except Exception:
        return {
            "retrieved_context": [],
            "error": "Travel knowledge retrieval failed.",
        }

    return {
        "retrieved_context": retrieved_context,
        "error": None,
    }
