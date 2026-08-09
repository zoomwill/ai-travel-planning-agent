"""Build and compile the deterministic travel-planning LangGraph runtime."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graphs.nodes import planner_node, router_node
from app.graphs.nodes.retriever import ContextRetriever, retriever_node
from app.graphs.state import TravelPlanState
from app.rag.retriever import retrieve_travel_context

TravelPlanningGraph = CompiledStateGraph[
    TravelPlanState,
    None,
    TravelPlanState,
    TravelPlanState,
]


def build_travel_planning_graph(
    context_retriever: ContextRetriever = retrieve_travel_context,
) -> TravelPlanningGraph:
    """Compile START-to-Router-to-Retriever-to-Planner-to-END."""

    def configured_retriever_node(state: TravelPlanState) -> TravelPlanState:
        """Run the Retriever node with this graph's injected dependency."""

        return retriever_node(state, context_retriever=context_retriever)

    builder = StateGraph(TravelPlanState)
    builder.add_node("router", router_node)
    builder.add_node("retriever", configured_retriever_node)
    builder.add_node("planner", planner_node)
    builder.add_edge(START, "router")
    builder.add_edge("router", "retriever")
    builder.add_edge("retriever", "planner")
    builder.add_edge("planner", END)
    return builder.compile(name="deterministic-travel-planning-agent")


travel_planning_graph = build_travel_planning_graph()
