"""Stable public names shared by MCP servers, clients, and backends."""

from typing import Final, Literal, TypeAlias

from app.search.models import SearchKind

ToolName: TypeAlias = Literal[
    "search_flights",
    "search_hotels",
    "search_attractions",
    "get_weather",
    "get_route",
]
ServerName: TypeAlias = Literal["local_tools", "travel_tools"]

LOCAL_SERVER_NAME: Final[ServerName] = "local_tools"
TRAVEL_SERVER_NAME: Final[ServerName] = "travel_tools"

LOCAL_TOOL_NAMES: Final[tuple[ToolName, ...]] = ("get_route", "get_weather")
TRAVEL_TOOL_NAMES: Final[tuple[ToolName, ...]] = (
    "search_attractions",
    "search_flights",
    "search_hotels",
)
EXPECTED_TOOL_NAMES: Final[tuple[ToolName, ...]] = tuple(
    sorted((*LOCAL_TOOL_NAMES, *TRAVEL_TOOL_NAMES))
)

SEARCH_KIND_TO_TOOL: Final[dict[SearchKind, ToolName]] = {
    SearchKind.FLIGHTS: "search_flights",
    SearchKind.HOTELS: "search_hotels",
    SearchKind.ATTRACTIONS: "search_attractions",
    SearchKind.WEATHER: "get_weather",
    SearchKind.ROUTE: "get_route",
}


def server_for_tool(tool_name: ToolName) -> ServerName:
    """Return the independent local server that owns a public tool name."""

    if tool_name in LOCAL_TOOL_NAMES:
        return LOCAL_SERVER_NAME
    return TRAVEL_SERVER_NAME
