"""Fan-in node that summarizes reducer-merged travel search results."""

from app.graphs.state import TravelPlanState
from app.search.models import (
    SEARCH_KIND_ORDER,
    SearchKindValue,
    SearchResultEnvelope,
    SearchSummary,
    SearchSummaryEntry,
    search_kind_value,
)


def aggregate_search_results_node(state: TravelPlanState) -> TravelPlanState:
    """Build one stable summary after every parallel worker has completed."""

    result_by_kind: dict[SearchKindValue, SearchResultEnvelope] = {
        result["kind"]: result for result in state.get("search_results", [])
    }
    error_kinds = {error["kind"] for error in state.get("tool_errors", [])}
    summary: SearchSummary = {}

    for kind in SEARCH_KIND_ORDER:
        kind_value = search_kind_value(kind)
        result = result_by_kind.get(kind_value)
        if result is not None and result["data"] and kind_value not in error_kinds:
            entry = SearchSummaryEntry(status="ok", count=len(result["data"]))
        else:
            entry = SearchSummaryEntry(status="error", count=0)
        summary[kind_value] = entry

    return {"search_summary": summary}
