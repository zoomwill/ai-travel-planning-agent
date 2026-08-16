"""JSON-safe, secret-free diagnostics for the local MCP tool layer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.mcp_tools.protocol import EXPECTED_TOOL_NAMES


class MCPServerStatus(BaseModel):
    """Public status for one independent MCP server connection."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "http"]
    ready: bool
    tools: list[str] = Field(default_factory=list)


class MCPDiagnostics(BaseModel):
    """Sanitized discovery state returned by the local status API."""

    model_config = ConfigDict(extra="forbid")

    backend_mode: Literal["direct", "mcp"]
    initialized: bool
    ready: bool
    servers: dict[str, MCPServerStatus] = Field(default_factory=dict)
    expected_tools: list[str] = Field(default_factory=list)
    discovered_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    duplicate_tools: list[str] = Field(default_factory=list)
    expected_tool_count: int = Field(ge=0)
    discovered_tool_count: int = Field(ge=0)
    last_error_type: str | None = None


def direct_mode_diagnostics() -> MCPDiagnostics:
    """Explain that the default direct backend intentionally has no MCP client."""

    expected = list(EXPECTED_TOOL_NAMES)
    return MCPDiagnostics(
        backend_mode="direct",
        initialized=False,
        ready=True,
        expected_tools=expected,
        expected_tool_count=len(expected),
        discovered_tool_count=0,
    )


def unavailable_mcp_diagnostics() -> MCPDiagnostics:
    """Return a safe status if MCP initialization failed before discovery completed."""

    expected = list(EXPECTED_TOOL_NAMES)
    return MCPDiagnostics(
        backend_mode="mcp",
        initialized=False,
        ready=False,
        expected_tools=expected,
        missing_tools=expected,
        expected_tool_count=len(expected),
        discovered_tool_count=0,
        last_error_type="mcp_discovery_failed",
    )
