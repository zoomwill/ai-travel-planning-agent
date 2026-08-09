"""Build and compile the deterministic Phase P05 LangGraph runtime."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graphs.nodes import planner_node, router_node
from app.graphs.state import TravelPlanState

TravelPlanningGraph = CompiledStateGraph[
    TravelPlanState,
    None,
    TravelPlanState,
    TravelPlanState,
]


def build_travel_planning_graph() -> TravelPlanningGraph:
    """Compile the fixed START-to-Router-to-Planner-to-END workflow."""

    builder = StateGraph(TravelPlanState)
    builder.add_node("router", router_node)
    builder.add_node("planner", planner_node)
    builder.add_edge(START, "router")
    builder.add_edge("router", "planner")
    builder.add_edge("planner", END)
    return builder.compile(name="deterministic-travel-planning-agent")


travel_planning_graph = build_travel_planning_graph()
