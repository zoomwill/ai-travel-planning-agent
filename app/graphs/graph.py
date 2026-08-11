"""Build and compile the deterministic travel-planning LangGraph runtime."""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.graphs.context import TravelRuntimeContext
from app.graphs.nodes import memory_context_node, planner_node, router_node
from app.graphs.nodes.retriever import ContextRetriever, retriever_node
from app.graphs.state import TravelPlanState
from app.rag.retriever import retrieve_travel_context

TravelPlanningGraph = CompiledStateGraph[
    TravelPlanState,
    TravelRuntimeContext,
    TravelPlanState,
    TravelPlanState,
]


def build_travel_planning_graph(
    context_retriever: ContextRetriever = retrieve_travel_context,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
) -> TravelPlanningGraph:
    """Compile the deterministic graph with optional persistence dependencies."""

    def configured_retriever_node(state: TravelPlanState) -> TravelPlanState:
        """Run the Retriever node with this graph's injected dependency."""

        return retriever_node(state, context_retriever=context_retriever)

    builder = StateGraph(TravelPlanState, context_schema=TravelRuntimeContext)
    builder.add_node("memory_context", memory_context_node)
    builder.add_node("router", router_node)
    builder.add_node("retriever", configured_retriever_node)
    builder.add_node("planner", planner_node)
    builder.add_edge(START, "memory_context")
    builder.add_edge("memory_context", "router")
    builder.add_edge("router", "retriever")
    builder.add_edge("retriever", "planner")
    builder.add_edge("planner", END)
    return builder.compile(
        checkpointer=checkpointer,
        store=store,
        name="deterministic-travel-planning-agent",
    )


travel_planning_graph = build_travel_planning_graph()
