"""Sanitized errors for MCP discovery, invocation, and validation boundaries."""

from typing import Literal, TypeAlias

MCPErrorType: TypeAlias = Literal[
    "mcp_tool_not_found",
    "mcp_discovery_failed",
    "mcp_transport_unavailable",
    "mcp_tool_timeout",
    "mcp_tool_failed",
    "mcp_invalid_response",
    "mcp_duplicate_tool",
]


class MCPToolLayerError(RuntimeError):
    """Carry a stable public error code without retaining a raw payload."""

    def __init__(
        self,
        error_type: MCPErrorType,
        safe_message: str,
        *,
        recoverable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.error_type = error_type
        self.safe_message = safe_message
        self.recoverable = recoverable
