"""Local-only Streamable HTTP FastMCP server for travel searches."""

import argparse
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

mcp = FastMCP("travel-search-tools", mask_error_details=True)


def _request_is_current(request: MCPToolRequest) -> bool:
    """Reject request metadata that does not match its validated requirements."""

    requirements = request.requirements.to_domain()
    return request.request_fingerprint == create_request_fingerprint(requirements)


@mcp.tool
async def search_flights(request: MCPToolRequest) -> MCPToolResponse:
    """Return deterministic flights from the existing P03 provider."""

    try:
        if not _request_is_current(request):
            return failed_response(request, "search_flights", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await asyncio.to_thread(mock_providers.search_flights, requirements)
        return successful_response(
            request,
            "search_flights",
            [dump_model_json(result) for result in results],
        )
    except Exception:
        return failed_response(request, "search_flights")


@mcp.tool
async def search_hotels(request: MCPToolRequest) -> MCPToolResponse:
    """Return deterministic hotels from the existing P03 provider."""

    try:
        if not _request_is_current(request):
            return failed_response(request, "search_hotels", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await asyncio.to_thread(mock_providers.search_hotels, requirements)
        return successful_response(
            request,
            "search_hotels",
            [dump_model_json(result) for result in results],
        )
    except Exception:
        return failed_response(request, "search_hotels")


@mcp.tool
async def search_attractions(request: MCPToolRequest) -> MCPToolResponse:
    """Return deterministic attractions from the existing P03 provider."""

    try:
        if not _request_is_current(request):
            return failed_response(request, "search_attractions", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await asyncio.to_thread(mock_providers.search_attractions, requirements)
        return successful_response(
            request,
            "search_attractions",
            [dump_model_json(result) for result in results],
        )
    except Exception:
        return failed_response(request, "search_attractions")


def _parse_args() -> argparse.Namespace:
    """Read only local HTTP transport options, never application secrets."""

    parser = argparse.ArgumentParser(description="Run local travel MCP tools over HTTP.")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", default=9001, type=int)
    parser.add_argument("--path", default="/mcp")
    return parser.parse_args()


def main() -> None:
    """Run local Streamable HTTP and handle an operator's Ctrl+C cleanly."""

    arguments = _parse_args()
    try:
        mcp.run(
            transport="http",
            host=arguments.host,
            port=arguments.port,
            path=arguments.path,
        )
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
