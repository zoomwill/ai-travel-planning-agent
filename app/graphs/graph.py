"""Build and compile the deterministic travel-planning LangGraph runtime."""

from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.graphs.context import TravelRuntimeContext
from app.graphs.nodes import (
    aggregate_search_results_node,
    finalize_plan_node,
    initialize_review_cycle_node,
    memory_context_node,
    planner_node,
    prepare_search_tasks_node,
    router_node,
)
from app.graphs.nodes.planner import route_after_planner
from app.graphs.nodes.prepare_search_tasks import dispatch_search_tasks
from app.graphs.nodes.retriever import ContextRetriever, advanced_retriever_node
from app.graphs.nodes.reviewer import reviewer_node, route_after_review
from app.graphs.nodes.search_worker import search_worker_node
from app.graphs.state import TravelPlanState
from app.rag.advanced_retriever import AdvancedRetriever
from app.rag.retriever import retrieve_travel_context
from app.review.reviewer import DeterministicPlanReviewer, PlanReviewer
from app.search.backend import DeterministicMockSearchBackend, SearchBackend
from app.search.models import SearchWorkerInput

TravelPlanningGraph = CompiledStateGraph[
    TravelPlanState,
    TravelRuntimeContext,
    TravelPlanState,
    TravelPlanState,
]


def build_travel_planning_graph(
    context_retriever: ContextRetriever = retrieve_travel_context,
    *,
    advanced_retriever: AdvancedRetriever | None = None,
    search_backend: SearchBackend | None = None,
    plan_reviewer: PlanReviewer | None = None,
    review_score_threshold: float = 80.0,
    review_max_rounds: int = 3,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
) -> TravelPlanningGraph:
    """Compile the deterministic graph with optional persistence dependencies."""

    backend = search_backend or DeterministicMockSearchBackend()
    reviewer = plan_reviewer or DeterministicPlanReviewer()

    async def configured_retriever_node(state: TravelPlanState) -> dict[str, Any]:
        """Run the Retriever node with this graph's injected dependency."""

        return await advanced_retriever_node(
            state,
            context_retriever=context_retriever,
            advanced_retriever=advanced_retriever,
        )

    async def configured_search_worker_node(
        worker_input: SearchWorkerInput,
    ) -> TravelPlanState:
        """Run one Send payload with this graph's injected search backend."""

        return await search_worker_node(worker_input, backend=backend)

    async def configured_reviewer_node(state: TravelPlanState) -> TravelPlanState:
        """Run Reviewer with this graph's injected policy and scoring settings."""

        return await reviewer_node(
            state,
            reviewer=reviewer,
            score_threshold=review_score_threshold,
            max_review_rounds=review_max_rounds,
        )

    builder = StateGraph(TravelPlanState, context_schema=TravelRuntimeContext)
    builder.add_node("memory_context", memory_context_node)
    builder.add_node("router", router_node)
    builder.add_node("retriever", configured_retriever_node)
    builder.add_node("prepare_search_tasks", prepare_search_tasks_node)
    builder.add_node(
        "search_worker",
        cast(Any, configured_search_worker_node),
        input_schema=SearchWorkerInput,
    )
    builder.add_node("aggregate_search_results", aggregate_search_results_node)
    builder.add_node("initialize_review_cycle", initialize_review_cycle_node)
    builder.add_node("planner", planner_node)
    builder.add_node("reviewer", configured_reviewer_node)
    builder.add_node("finalize_plan", finalize_plan_node)
    builder.add_edge(START, "memory_context")
    builder.add_edge("memory_context", "router")
    builder.add_edge("router", "retriever")
    builder.add_edge("retriever", "prepare_search_tasks")
    builder.add_conditional_edges(
        "prepare_search_tasks",
        dispatch_search_tasks,
        ["search_worker", "aggregate_search_results"],
    )
    builder.add_edge("search_worker", "aggregate_search_results")
    builder.add_edge("aggregate_search_results", "initialize_review_cycle")
    builder.add_edge("initialize_review_cycle", "planner")
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        ["reviewer", END],
    )
    builder.add_conditional_edges(
        "reviewer",
        route_after_review,
        ["planner", "finalize_plan"],
    )
    builder.add_edge("finalize_plan", END)
    return builder.compile(
        checkpointer=checkpointer,
        store=store,
        name="deterministic-travel-planning-agent",
    )
