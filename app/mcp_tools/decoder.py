"""Decode only documented MCP/LangChain public result shapes."""

import json
from collections.abc import Mapping
from typing import Any, cast

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.models import MCPToolResponse


def _decode_json_text(value: str) -> object:
    """Parse a complete JSON document without guessing from natural language."""

    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise MCPToolLayerError(
            "mcp_invalid_response",
            "The MCP tool returned malformed JSON.",
            recoverable=False,
        ) from exc


def _artifact_content(message: ToolMessage) -> object | None:
    """Read LangChain's public structured-content artifact when present."""

    artifact = message.artifact
    if isinstance(artifact, Mapping):
        structured = artifact.get("structured_content")
        if structured is not None:
            return cast(object, structured)
    return None


def _text_block_content(value: object) -> object:
    """Accept the adapter's actual one-text-block fallback shape."""

    if not isinstance(value, list) or len(value) != 1:
        return value
    block = value[0]
    if not isinstance(block, Mapping) or block.get("type") != "text":
        return value
    text = block.get("text")
    if not isinstance(text, str):
        return value
    return _decode_json_text(text)


def decode_mcp_tool_response(result: object) -> MCPToolResponse:
    """Validate dict, JSON text, or public ToolMessage results as one envelope."""

    candidate: object = result
    if isinstance(result, ToolMessage):
        candidate = _artifact_content(result)
        if candidate is None:
            candidate = result.content
    if isinstance(candidate, str):
        candidate = _decode_json_text(candidate)
    else:
        candidate = _text_block_content(candidate)
    try:
        return MCPToolResponse.model_validate(candidate)
    except (ValidationError, TypeError, ValueError) as exc:
        raise MCPToolLayerError(
            "mcp_invalid_response",
            "The MCP tool returned an invalid response envelope.",
            recoverable=False,
        ) from exc


def structured_content_from_result(result: object) -> dict[str, Any] | None:
    """Expose structured content for diagnostics tests without private objects."""

    if not isinstance(result, ToolMessage):
        return None
    content = _artifact_content(result)
    if isinstance(content, dict):
        return content
    return None
