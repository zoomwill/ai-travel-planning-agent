"""Prepare and dispatch deterministic travel-search fan-out work."""

from typing import Any

from langgraph.types import Overwrite, Send

from app.graphs.state import TravelPlanState
from app.search.models import SearchWorkerInput, create_search_tasks, dump_model_json


def _reset_search_state() -> dict[str, Any]:
    """Return reducer-bypassing empty values for a new request on any thread."""

    return {
        "search_tasks": Overwrite(value=[]),
        "search_results": Overwrite(value=[]),
        "tool_errors": Overwrite(value=[]),
        "search_summary": Overwrite(value={}),
    }


def prepare_search_tasks_node(state: TravelPlanState) -> dict[str, Any]:
    """Create five tasks without running a provider or generating a plan."""

    update = _reset_search_state()
    if state.get("error") is not None:
        update["error"] = state["error"]
        return update
    if state.get("next_agent") != "planner":
        update["error"] = "The search subagents were not selected."
        return update

    requirements = state.get("requirements")
    if requirements is None:
        update["error"] = "Validated trip requirements are required for search."
        return update

    update["search_tasks"] = Overwrite(value=create_search_tasks(requirements))
    update["error"] = None
    return update


def dispatch_search_tasks(state: TravelPlanState) -> str | list[Send]:
    """Fan out five minimal JSON-safe worker payloads through LangGraph Send."""

    requirements = state.get("requirements")
    tasks = state.get("search_tasks", [])
    if state.get("error") is not None or requirements is None or not tasks:
        return "aggregate_search_results"

    requirements_data = dump_model_json(requirements)
    return [
        Send(
            "search_worker",
            SearchWorkerInput(
                search_task=task,
                requirements_data=requirements_data,
            ),
        )
        for task in tasks
    ]
