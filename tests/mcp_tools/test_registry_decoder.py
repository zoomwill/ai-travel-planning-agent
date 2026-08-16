"""Unit tests for registry conflict policy and public result decoding."""

import json

import pytest
from langchain_core.messages import ToolMessage

from app.mcp_tools.decoder import decode_mcp_tool_response
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.protocol import EXPECTED_TOOL_NAMES
from app.mcp_tools.registry import MCPToolRegistry
from tests.mcp_tools.helpers import async_tool, response


async def _unused_handler(_: dict[str, object]) -> tuple[str, dict[str, object]]:
    return "{}", {}


def _tool(name: str):
    return async_tool(name, _unused_handler)


def test_registry_is_sorted_and_order_independent() -> None:
    registry = MCPToolRegistry([_tool(name) for name in reversed(EXPECTED_TOOL_NAMES)])

    registry.validate_expected_tools()

    assert registry.list_tool_names() == list(EXPECTED_TOOL_NAMES)


def test_registry_rejects_missing_duplicate_and_unknown_names() -> None:
    with pytest.raises(MCPToolLayerError) as missing:
        MCPToolRegistry([_tool("get_weather")]).validate_expected_tools()
    assert missing.value.error_type == "mcp_discovery_failed"

    with pytest.raises(MCPToolLayerError) as duplicate:
        MCPToolRegistry([_tool("get_weather"), _tool("get_weather")])
    assert duplicate.value.error_type == "mcp_duplicate_tool"

    registry = MCPToolRegistry([])
    with pytest.raises(MCPToolLayerError) as not_found:
        registry.get_tool("unknown")
    assert not_found.value.error_type == "mcp_tool_not_found"


def test_decoder_supports_dict_json_and_actual_tool_message_artifact() -> None:
    envelope = response("get_weather", data=[{"city": "Tokyo"}])
    payload = envelope.model_dump(mode="json")
    message = ToolMessage(
        content="non-structured fallback",
        tool_call_id="call",
        artifact={"structured_content": payload},
    )

    assert decode_mcp_tool_response(payload) == envelope
    assert decode_mcp_tool_response(json.dumps(payload)) == envelope
    assert decode_mcp_tool_response(message) == envelope


def test_decoder_accepts_adapter_text_block_fallback_but_not_malformed_data() -> None:
    payload = response("get_weather", data=[{"city": "Tokyo"}]).model_dump(mode="json")
    assert decode_mcp_tool_response([{"type": "text", "text": json.dumps(payload)}]).ok

    for malformed in ("not JSON", {"secret": "raw-payload"}, [{"type": "image"}]):
        with pytest.raises(MCPToolLayerError) as captured:
            decode_mcp_tool_response(malformed)
        assert captured.value.error_type == "mcp_invalid_response"
        assert "raw-payload" not in str(captured.value)
