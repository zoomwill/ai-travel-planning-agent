"""Tests for the deterministic Retriever Agent node."""

from app.graphs.nodes.retriever import retriever_node
from app.graphs.state import TravelPlanState


def test_retriever_node_writes_context_into_state() -> None:
    """A planning request receives injected local knowledge."""

    queries: list[str] = []

    def retrieve(query: str) -> list[str]:
        queries.append(query)
        return ["Yanaka is suitable for street photography."]

    state: TravelPlanState = {
        "user_request": "Tokyo photography travel plan",
        "next_agent": "planner",
        "error": None,
    }

    update = retriever_node(state, context_retriever=retrieve)

    assert queries == ["Tokyo photography travel plan"]
    assert update == {
        "retrieved_context": ["Yanaka is suitable for street photography."],
        "error": None,
    }


def test_retriever_node_does_not_run_for_rejected_intent() -> None:
    """A Router rejection cannot accidentally query Chroma."""

    def unexpected_retrieve(query: str) -> list[str]:
        raise AssertionError(f"retriever should not receive {query}")

    update = retriever_node(
        {
            "user_request": "Explain Python",
            "next_agent": None,
            "error": "The request does not describe a travel plan.",
        },
        context_retriever=unexpected_retrieve,
    )

    assert update["retrieved_context"] == []
    assert update["error"] == "The request does not describe a travel plan."


def test_retriever_node_hides_internal_failure_details() -> None:
    """A raw vector-store exception becomes a safe graph-state error."""

    def failing_retrieve(query: str) -> list[str]:
        del query
        raise RuntimeError("private Chroma detail")

    update = retriever_node(
        {
            "user_request": "plan Tokyo trip",
            "next_agent": "planner",
            "error": None,
        },
        context_retriever=failing_retrieve,
    )

    assert update == {
        "retrieved_context": [],
        "error": "Travel knowledge retrieval failed.",
    }
