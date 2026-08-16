"""Small deterministic MCP test fixtures."""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.domain.models import TripRequirements
from app.mcp_tools.models import MCPToolRequest, MCPToolResponse, MCPTripRequirements
from app.search.models import create_request_fingerprint


def requirements() -> TripRequirements:
    """Return one fixed request shared by MCP unit tests."""

    return TripRequirements.model_validate(
        {
            "origin": "Shanghai",
            "destination": "Tokyo",
            "start_date": "2027-04-10",
            "end_date": "2027-04-12",
            "budget": "12000.00",
            "currency": "CNY",
            "travelers": 2,
            "preferences": ["museums"],
        }
    )


def request() -> MCPToolRequest:
    """Build one traceable JSON-safe MCP request."""

    domain = requirements()
    return MCPToolRequest(
        task_id="unit-task",
        request_fingerprint=create_request_fingerprint(domain),
        requirements=MCPTripRequirements.from_domain(domain),
    )


def response(tool_name: str, *, data: Any) -> MCPToolResponse:
    """Build one successful response tied to the shared request."""

    tool_request = request()
    return MCPToolResponse(
        ok=True,
        tool_name=tool_name,
        task_id=tool_request.task_id,
        request_fingerprint=tool_request.request_fingerprint,
        data=data,
    )


def async_tool(
    name: str,
    handler: Callable[[dict[str, object]], Awaitable[tuple[str, dict[str, object]]]],
) -> BaseTool:
    """Create a public StructuredTool that returns content plus an artifact."""

    return StructuredTool.from_function(
        coroutine=handler,
        name=name,
        description=f"Test tool {name}",
        response_format="content_and_artifact",
    )
