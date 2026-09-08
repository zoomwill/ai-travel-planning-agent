"""Local-only Streamable HTTP FastMCP server for travel searches."""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastmcp import Context, FastMCP
from pydantic import BaseModel

from app.core.config import Settings
from app.domain.models import TravelDataSource, TripRequirements
from app.external.duffel.errors import DuffelError
from app.external.liteapi.errors import LiteAPIError
from app.external.runtime import TravelProviderRuntime, create_travel_runtime
from app.mcp_tools.models import (
    MCPToolRequest,
    MCPToolResponse,
    failed_response,
    successful_response,
)
from app.search.backend import DeterministicMockSearchBackend, SearchBackend
from app.search.models import SearchKind, create_request_fingerprint, dump_model_json


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Let this independent process own and close its own Duffel client."""

    settings = Settings()
    runtime: TravelProviderRuntime | None = None
    backend: SearchBackend = DeterministicMockSearchBackend()
    if settings.travel_data_mode != "demo":
        runtime = create_travel_runtime(settings)
        backend = runtime.backend
    try:
        yield {"search_backend": backend}
    finally:
        if runtime is not None:
            await runtime.aclose()


mcp = FastMCP("travel-search-tools", mask_error_details=True, lifespan=_lifespan)


def _request_is_current(request: MCPToolRequest) -> bool:
    """Reject request metadata that does not match its validated requirements."""

    requirements = request.requirements.to_domain()
    return request.request_fingerprint == create_request_fingerprint(requirements)


def _backend(context: Context) -> SearchBackend:
    """Read only the process-owned backend from FastMCP lifespan state."""

    return cast(SearchBackend, context.lifespan_context["search_backend"])


def _source(results: list[BaseModel], backend: SearchBackend, kind: SearchKind) -> TravelDataSource:
    """Return actual result provenance, including explicit demo fallback."""

    if results:
        return TravelDataSource(results[0].model_dump()["data_source"])
    return backend.source_for(kind)


def _safe_failure(
    request: MCPToolRequest,
    tool_name: str,
    backend: SearchBackend,
    kind: SearchKind,
    exception: Exception,
) -> MCPToolResponse:
    """Convert provider failures without response bodies, tokens, or tracebacks."""

    if isinstance(exception, (DuffelError, LiteAPIError)):
        return failed_response(
            request,
            tool_name,
            error_type=exception.code,
            recoverable=exception.recoverable,
            source=backend.source_for(kind),
        )
    return failed_response(request, tool_name, source=backend.source_for(kind))


@mcp.tool
async def search_flights(request: MCPToolRequest, ctx: Context) -> MCPToolResponse:
    """Return configured demo or Duffel flights without receiving provider secrets."""

    backend = _backend(ctx)
    try:
        if not _request_is_current(request):
            return failed_response(request, "search_flights", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await backend.search_flights(requirements)
        return successful_response(
            request,
            "search_flights",
            [dump_model_json(result) for result in results],
            source=_source(list(results), backend, SearchKind.FLIGHTS),
        )
    except Exception as exc:
        return _safe_failure(request, "search_flights", backend, SearchKind.FLIGHTS, exc)


@mcp.tool
async def search_hotels(request: MCPToolRequest, ctx: Context) -> MCPToolResponse:
    """Return configured demo or Duffel stays without receiving provider secrets."""

    backend = _backend(ctx)
    try:
        if not _request_is_current(request):
            return failed_response(request, "search_hotels", error_type="invalid_request")
        requirements = request.requirements.to_domain()
        results = await backend.search_hotels(requirements)
        return successful_response(
            request,
            "search_hotels",
            [dump_model_json(result) for result in results],
            source=_source(list(results), backend, SearchKind.HOTELS),
        )
    except Exception as exc:
        return _safe_failure(request, "search_hotels", backend, SearchKind.HOTELS, exc)


@mcp.tool
async def search_attractions(request: MCPToolRequest, ctx: Context) -> MCPToolResponse:
    """Keep attraction data deterministic in every P17 data mode."""

    backend = _backend(ctx)
    try:
        if not _request_is_current(request):
            return failed_response(request, "search_attractions", error_type="invalid_request")
        requirements: TripRequirements = request.requirements.to_domain()
        results = await backend.search_attractions(requirements)
        return successful_response(
            request,
            "search_attractions",
            [dump_model_json(result) for result in results],
            source=_source(list(results), backend, SearchKind.ATTRACTIONS),
        )
    except Exception as exc:
        return _safe_failure(
            request,
            "search_attractions",
            backend,
            SearchKind.ATTRACTIONS,
            exc,
        )


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
