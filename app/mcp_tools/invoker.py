"""Bounded asynchronous invocation for discovered LangChain MCP tools."""

import asyncio
from dataclasses import dataclass
from typing import cast

from langchain_core.messages import ToolCall
from pydantic import ValidationError

from app.mcp_tools.decoder import decode_mcp_tool_response
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.models import MCPToolRequest, MCPToolResponse
from app.mcp_tools.registry import MCPToolRegistry


@dataclass(slots=True)
class MCPToolInvoker:
    """Invoke one registered tool with timeout and bounded transient retry."""

    registry: MCPToolRegistry
    timeout_seconds: float
    max_retries: int

    async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
        """Call `BaseTool.ainvoke()` and validate its structured envelope."""

        tool = self.registry.get_tool(tool_name)
        tool_call = cast(
            ToolCall,
            {
                "name": tool_name,
                "args": {"request": request.model_dump(mode="json")},
                "id": request.task_id,
                "type": "tool_call",
            },
        )
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                raw_result = await asyncio.wait_for(
                    tool.ainvoke(tool_call),
                    timeout=self.timeout_seconds,
                )
                response = decode_mcp_tool_response(raw_result)
                self._validate_response(response, tool_name, request)
                return response
            except MCPToolLayerError:
                raise
            except TimeoutError as exc:
                if attempt + 1 < attempts:
                    continue
                raise MCPToolLayerError(
                    "mcp_tool_timeout",
                    "The MCP tool exceeded its configured timeout.",
                    recoverable=True,
                ) from exc
            except (ValidationError, ValueError) as exc:
                raise MCPToolLayerError(
                    "mcp_tool_failed",
                    "The MCP tool rejected its validated input.",
                    recoverable=False,
                ) from exc
            except Exception as exc:
                if attempt + 1 < attempts:
                    continue
                raise MCPToolLayerError(
                    "mcp_transport_unavailable",
                    "The MCP tool transport is unavailable.",
                    recoverable=True,
                ) from exc
        raise AssertionError("bounded MCP attempts were exhausted without a result")

    @staticmethod
    def _validate_response(
        response: MCPToolResponse,
        tool_name: str,
        request: MCPToolRequest,
    ) -> None:
        """Reject cross-request responses and sanitized server error envelopes."""

        if (
            response.tool_name != tool_name
            or response.task_id != request.task_id
            or response.request_fingerprint != request.request_fingerprint
        ):
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "The MCP response metadata did not match the request.",
                recoverable=False,
            )
        if not response.ok:
            error = response.error
            raise MCPToolLayerError(
                "mcp_tool_failed",
                error.safe_message if error is not None else "The MCP tool failed.",
                recoverable=error.recoverable if error is not None else False,
            )
