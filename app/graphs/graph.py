"""Build and compile the deterministic travel-planning LangGraph runtime."""

from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.graphs.context import TravelRuntimeContext
from app.graphs.nodes import (
    aggregate_search_results_node,
    memory_context_node,
    planner_node,
    prepare_search_tasks_node,
    router_node,
)
from app.graphs.nodes.prepare_search_tasks import dispatch_search_tasks
from app.graphs.nodes.retriever import ContextRetriever, retriever_node
from app.graphs.nodes.search_worker import search_worker_node
from app.graphs.state import TravelPlanState
from app.rag.retriever import retrieve_travel_context
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
    search_backend: SearchBackend | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
) -> TravelPlanningGraph:
    """Compile the deterministic graph with optional persistence dependencies."""

    backend = search_backend or DeterministicMockSearchBackend()

    def configured_retriever_node(state: TravelPlanState) -> TravelPlanState:
        """Run the Retriever node with this graph's injected dependency."""

        return retriever_node(state, context_retriever=context_retriever)

    async def configured_search_worker_node(
        worker_input: SearchWorkerInput,
    ) -> TravelPlanState:
        """Run one Send payload with this graph's injected search backend."""

        return await search_worker_node(worker_input, backend=backend)

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
    builder.add_node("planner", planner_node)
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
    builder.add_edge("aggregate_search_results", "planner")
    builder.add_edge("planner", END)
    return builder.compile(
        checkpointer=checkpointer,
        store=store,
        name="deterministic-travel-planning-agent",
    )


travel_planning_graph = build_travel_planning_graph()
