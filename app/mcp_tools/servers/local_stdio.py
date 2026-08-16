"""STDIO FastMCP server for deterministic weather and route tools."""

import asyncio

from fastmcp import FastMCP

from app.mcp_tools.models import (
    MCPToolRequest,
    MCPToolResponse,
    failed_response,
    successful_response,
)
from app.search.models import create_request_fingerprint, dump_model_json
from app.services import mock_providers

mcp = FastMCP("travel-local-tools", mask_error_details=True)


def _request_is_current(request: MCPToolRequest) -> bool:
    """Reject request metadata that does not match its validated requirements."""

    requirements = request.requirements.to_domain()
    return request.request_fingerprint == create_request_fingerprint(requirements)


@mcp.tool
async def get_weather(request: MCPToolRequest) -> MCPToolResponse:
    """Return deterministic weather for every requested travel date."""

    try:
        if not _request_is_current(request):
            return failed_response(request, "get_weather", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await asyncio.to_thread(mock_providers.get_weather, requirements)
        return successful_response(
            request,
            "get_weather",
            [dump_model_json(result) for result in results],
        )
    except Exception:
        return failed_response(request, "get_weather")


@mcp.tool
async def get_route(request: MCPToolRequest) -> MCPToolResponse:
    """Return one deterministic route between the supplied route endpoints."""

    try:
        if not _request_is_current(request):
            return failed_response(request, "get_route", error_type="invalid_request")
        origin = request.route_origin or request.requirements.origin
        destination = request.route_destination or request.requirements.destination
        result = await asyncio.to_thread(mock_providers.get_route, origin, destination)
        return successful_response(request, "get_route", dump_model_json(result))
    except Exception:
        return failed_response(request, "get_route")


def main() -> None:
    """Run STDIO until its owning client closes the subprocess."""

    try:
        mcp.run()
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
