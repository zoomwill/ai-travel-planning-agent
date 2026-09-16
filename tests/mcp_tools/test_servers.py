"""In-memory FastMCP tests that never open ports or spawn subprocesses."""

import pytest
from fastmcp import Client

from app.domain.models import (
    Attraction,
    FlightOption,
    HotelOption,
    RouteSummary,
    WeatherSummary,
)
from app.mcp_tools.models import MCPToolResponse
from app.mcp_tools.servers.local_stdio import mcp as local_mcp
from app.mcp_tools.servers.travel_http import mcp as travel_mcp
from tests.mcp_tools.helpers import request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server", "expected_names"),
    [
        (local_mcp, ["get_route", "get_weather"]),
        (travel_mcp, ["search_attractions", "search_flights", "search_hotels"]),
    ],
)
async def test_servers_expose_only_expected_tools(
    server,
    expected_names: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAVEL_DATA_MODE", "demo")
    async with Client(server) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools) == expected_names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server", "tool_name", "model_type", "is_list"),
    [
        (local_mcp, "get_weather", WeatherSummary, True),
        (local_mcp, "get_route", RouteSummary, False),
        (travel_mcp, "search_flights", FlightOption, True),
        (travel_mcp, "search_hotels", HotelOption, True),
        (travel_mcp, "search_attractions", Attraction, True),
    ],
)
async def test_every_tool_returns_deterministic_domain_data(
    server,
    tool_name: str,
    model_type,
    is_list: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAVEL_DATA_MODE", "demo")
    payload = {"request": request().model_dump(mode="json")}
    if tool_name == "get_route":
        payload["request"]["route_origin"] = "Tokyo Station"
        payload["request"]["route_destination"] = "Asakusa"

    async with Client(server) as client:
        first = await client.call_tool(tool_name, payload)
        second = await client.call_tool(tool_name, payload)

    envelope = MCPToolResponse.model_validate(first.structured_content)
    assert first.structured_content == second.structured_content
    if tool_name == "get_route":
        assert envelope.ok is False
        assert envelope.data is None
        assert envelope.error is not None
        return
    assert envelope.ok is True
    if is_list:
        assert isinstance(envelope.data, list) and envelope.data
        assert all(model_type.model_validate(item) for item in envelope.data)
    else:
        assert model_type.model_validate(envelope.data)


@pytest.mark.asyncio
async def test_server_returns_safe_error_envelope_for_bad_fingerprint() -> None:
    tool_request = request().model_copy(update={"request_fingerprint": "wrong"})

    async with Client(local_mcp) as client:
        result = await client.call_tool(
            "get_weather",
            {"request": tool_request.model_dump(mode="json")},
        )

    envelope = MCPToolResponse.model_validate(result.structured_content)
    assert envelope.ok is False
    assert envelope.error is not None
    assert envelope.error.error_type == "invalid_request"
    assert "traceback" not in result.content[0].text.casefold()
