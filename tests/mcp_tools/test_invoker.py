"""Tests for bounded public BaseTool invocation behavior."""

import asyncio

import pytest

from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.invoker import MCPToolInvoker
from app.mcp_tools.registry import MCPToolRegistry
from tests.mcp_tools.helpers import async_tool, request, response


def _invoker(tool, *, retries: int = 0, timeout: float = 1) -> MCPToolInvoker:
    return MCPToolInvoker(MCPToolRegistry([tool]), timeout, retries)


@pytest.mark.asyncio
async def test_invoker_returns_validated_structured_artifact() -> None:
    async def handler(request: dict[str, object]):
        del request
        payload = response("get_weather", data=[{"city": "Tokyo"}]).model_dump(mode="json")
        return "fallback", {"structured_content": payload}

    result = await _invoker(async_tool("get_weather", handler)).invoke("get_weather", request())

    assert result.ok is True


@pytest.mark.asyncio
async def test_invoker_timeout_and_not_found_are_safe() -> None:
    async def slow(request: dict[str, object]):
        del request
        await asyncio.sleep(0.1)
        return "late", {}

    with pytest.raises(MCPToolLayerError) as timeout:
        await _invoker(async_tool("get_weather", slow), timeout=0.001).invoke(
            "get_weather", request()
        )
    assert timeout.value.error_type == "mcp_tool_timeout"

    with pytest.raises(MCPToolLayerError) as missing:
        await MCPToolInvoker(MCPToolRegistry([]), 1, 0).invoke("get_weather", request())
    assert missing.value.error_type == "mcp_tool_not_found"


@pytest.mark.asyncio
async def test_invoker_retries_transport_once_but_not_validation() -> None:
    calls = 0

    async def transient(request: dict[str, object]):
        nonlocal calls
        del request
        calls += 1
        if calls == 1:
            raise OSError("temporary transport detail")
        payload = response("get_weather", data=[{"city": "Tokyo"}]).model_dump(mode="json")
        return "ok", {"structured_content": payload}

    result = await _invoker(async_tool("get_weather", transient), retries=1).invoke(
        "get_weather", request()
    )
    assert result.ok and calls == 2

    invalid_calls = 0

    async def invalid(request: dict[str, object]):
        nonlocal invalid_calls
        del request
        invalid_calls += 1
        raise ValueError("invalid input detail")

    with pytest.raises(MCPToolLayerError) as captured:
        await _invoker(async_tool("get_weather", invalid), retries=3).invoke(
            "get_weather", request()
        )
    assert captured.value.error_type == "mcp_tool_failed"
    assert invalid_calls == 1
