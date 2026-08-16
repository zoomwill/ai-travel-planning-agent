"""Explicit local smoke check for both P11 MCP servers and all five tools."""

import asyncio

from app.core.config import Settings
from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    TripRequirements,
    WeatherSummary,
)
from app.mcp_tools.client import create_mcp_runtime
from app.mcp_tools.protocol import LOCAL_SERVER_NAME, TRAVEL_SERVER_NAME


async def check_tools() -> None:
    """Discover, invoke, and domain-validate the fixed local MCP tool set."""

    settings = Settings()
    runtime = await create_mcp_runtime(settings)
    diagnostics = runtime.diagnostics
    if not diagnostics.ready:
        error_type = diagnostics.last_error_type or "mcp_discovery_failed"
        raise RuntimeError(f"MCP discovery is not ready ({error_type}).")

    for server_name in (LOCAL_SERVER_NAME, TRAVEL_SERVER_NAME):
        server = diagnostics.servers[server_name]
        print(f"PASS discovered {server_name}:")
        for tool_name in server.tools:
            print(f"- {tool_name}")
    print(f"PASS total tools: {diagnostics.discovered_tool_count}")

    requirements = {
        "origin": "Shanghai",
        "destination": "Tokyo",
        "start_date": "2027-04-10",
        "end_date": "2027-04-12",
        "budget": "12000.00",
        "currency": "CNY",
        "travelers": 2,
        "preferences": ["museums"],
    }
    trip = TripRequirements.model_validate(requirements)
    checks = (
        all(isinstance(item, FlightOption) for item in await runtime.backend.search_flights(trip)),
        all(isinstance(item, HotelOption) for item in await runtime.backend.search_hotels(trip)),
        all(
            isinstance(item, Attraction) for item in await runtime.backend.search_attractions(trip)
        ),
        all(isinstance(item, WeatherSummary) for item in await runtime.backend.get_weather(trip)),
        isinstance(await runtime.backend.get_route(trip.origin, trip.destination), RouteSummary),
    )
    if not all(checks):
        raise RuntimeError("One or more MCP tools returned invalid domain data.")
    print("PASS all tool calls")


def main() -> int:
    """Print only safe PASS/FAIL output and return a shell-friendly status."""

    try:
        asyncio.run(check_tools())
    except Exception as exc:
        error_type = getattr(exc, "error_type", "mcp_check_failed")
        print(f"FAIL MCP tools: {error_type}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
