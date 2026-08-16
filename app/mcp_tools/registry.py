"""Order-independent registry for public LangChain MCP tool objects."""

from collections import Counter
from collections.abc import Sequence

from langchain_core.tools import BaseTool

from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.protocol import EXPECTED_TOOL_NAMES


class MCPToolRegistry:
    """Index discovered tools by public name and reject ambiguous discovery."""

    def __init__(self, tools: Sequence[BaseTool]) -> None:
        names = [tool.name for tool in tools]
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicates:
            raise MCPToolLayerError(
                "mcp_duplicate_tool",
                "MCP discovery returned duplicate tool names.",
                recoverable=False,
            )
        self._tools = {tool.name: tool for tool in tools}

    def get_tool(self, name: str) -> BaseTool:
        """Return one tool or raise a stable not-found error."""

        try:
            return self._tools[name]
        except KeyError as exc:
            raise MCPToolLayerError(
                "mcp_tool_not_found",
                "The requested MCP tool is not available.",
                recoverable=True,
            ) from exc

    def list_tool_names(self) -> list[str]:
        """Return stable names independent of server discovery order."""

        return sorted(self._tools)

    def validate_expected_tools(self, *, require_all: bool = True) -> None:
        """Reject missing required names and all unexpected tool capabilities."""

        names = set(self._tools)
        expected = set(EXPECTED_TOOL_NAMES)
        missing = expected - names
        unexpected = names - expected
        if unexpected or (require_all and missing):
            raise MCPToolLayerError(
                "mcp_discovery_failed",
                "MCP discovery did not return the expected travel tools.",
                recoverable=True,
            )
