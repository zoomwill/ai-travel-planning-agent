"""Stateless MultiServerMCPClient discovery and readiness lifecycle."""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from app.core.config import Settings
from app.mcp_tools.backend import MCPTravelSearchBackend
from app.mcp_tools.diagnostics import MCPDiagnostics, MCPServerStatus
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.invoker import MCPToolInvoker
from app.mcp_tools.protocol import (
    EXPECTED_TOOL_NAMES,
    LOCAL_SERVER_NAME,
    TRAVEL_SERVER_NAME,
)
from app.mcp_tools.registry import MCPToolRegistry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REFRESH_COOLDOWN_SECONDS = 1.0


def build_mcp_client(settings: Settings) -> MultiServerMCPClient:
    """Build fixed local connections without forwarding secrets or shell commands."""

    connections: dict[str, Connection] = {}
    if settings.mcp_enable_stdio_server:
        connections[LOCAL_SERVER_NAME] = cast(
            Connection,
            {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "app.mcp_tools.servers.local_stdio"],
                "cwd": str(_PROJECT_ROOT),
                "env": {"PYTHONUNBUFFERED": "1"},
            },
        )
    if settings.mcp_enable_http_server:
        connections[TRAVEL_SERVER_NAME] = cast(
            Connection,
            {
                "transport": "http",
                "url": settings.mcp_http_url,
                "timeout": settings.mcp_tool_timeout_seconds,
            },
        )
    return MultiServerMCPClient(connections, handle_tool_errors=False)


async def _discover_server(
    client: MultiServerMCPClient,
    server_name: str,
    timeout_seconds: float,
) -> tuple[list[BaseTool], bool]:
    """Discover one server with a deadline and no raw exception propagation."""

    try:
        tools = await asyncio.wait_for(
            client.get_tools(server_name=server_name),
            timeout=timeout_seconds,
        )
    except Exception:
        return [], False
    return tools, True


async def _discover(
    client: MultiServerMCPClient,
    settings: Settings,
) -> tuple[MCPToolRegistry, MCPDiagnostics]:
    """Discover enabled servers independently so partial tools remain diagnosable."""

    jobs = {
        name: _discover_server(client, name, settings.mcp_discovery_timeout_seconds)
        for name in client.connections
    }
    results = await asyncio.gather(*jobs.values()) if jobs else []
    discovered_by_server = dict(zip(jobs, results, strict=True))

    all_tools = [tool for tools, _ in discovered_by_server.values() for tool in tools]
    names = [tool.name for tool in all_tools]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    expected = set(EXPECTED_TOOL_NAMES)
    discovered = set(names)
    missing = sorted(expected - discovered)
    unexpected = sorted(discovered - expected)
    last_error_type: str | None = None

    try:
        registry = MCPToolRegistry(all_tools)
    except MCPToolLayerError as exc:
        registry = MCPToolRegistry([])
        last_error_type = exc.error_type
    else:
        try:
            registry.validate_expected_tools(require_all=settings.mcp_require_all_tools)
        except MCPToolLayerError as exc:
            last_error_type = exc.error_type

    server_statuses: dict[str, MCPServerStatus] = {}
    for name, raw_transport in (
        (LOCAL_SERVER_NAME, "stdio"),
        (TRAVEL_SERVER_NAME, "http"),
    ):
        transport = cast(Literal["stdio", "http"], raw_transport)
        if name in discovered_by_server:
            tools, connected = discovered_by_server[name]
            tool_names = sorted(tool.name for tool in tools)
            ready = connected and bool(tool_names)
        else:
            tool_names = []
            ready = False
        server_statuses[name] = MCPServerStatus(
            transport=transport,
            ready=ready,
            tools=tool_names,
        )

    ready = (
        not duplicates
        and not unexpected
        and (not missing or not settings.mcp_require_all_tools)
        and bool(discovered_by_server)
        and all(server_statuses[name].ready for name in discovered_by_server)
    )
    if not ready and last_error_type is None:
        last_error_type = "mcp_discovery_failed"
    diagnostics = MCPDiagnostics(
        backend_mode="mcp",
        initialized=True,
        ready=ready,
        servers=server_statuses,
        expected_tools=sorted(expected),
        discovered_tools=sorted(discovered),
        missing_tools=missing,
        duplicate_tools=duplicates,
        expected_tool_count=len(expected),
        discovered_tool_count=len(discovered),
        last_error_type=last_error_type,
    )
    return registry, diagnostics


@dataclass(slots=True)
class MCPRuntime:
    """Application-owned MCP discovery, backend, and bounded refresh state."""

    settings: Settings
    client: MultiServerMCPClient
    registry: MCPToolRegistry
    diagnostics: MCPDiagnostics
    invoker: MCPToolInvoker
    backend: MCPTravelSearchBackend
    _refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _next_refresh_time: float = 0.0

    async def refresh(self, *, force: bool = False) -> bool:
        """Refresh discovery at most once per cooldown unless explicitly forced."""

        async with self._refresh_lock:
            now = time.monotonic()
            if not force and now < self._next_refresh_time:
                return self.diagnostics.ready
            self._next_refresh_time = now + _REFRESH_COOLDOWN_SECONDS
            registry, diagnostics = await _discover(self.client, self.settings)
            self.registry = registry
            self.diagnostics = diagnostics
            self.invoker.registry = registry
            return diagnostics.ready

    async def is_ready(self) -> bool:
        """Combine cached discovery with a bounded local HTTP reachability check."""

        if self.settings.mcp_enable_http_server:
            if not await self._http_port_is_open():
                self._mark_http_unavailable()
                return False
        if self.diagnostics.ready:
            return True
        return await self.refresh()

    async def _http_port_is_open(self) -> bool:
        """Probe only the configured loopback socket without sending credentials."""

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.settings.mcp_http_host,
                    self.settings.mcp_http_port,
                ),
                timeout=self.settings.infrastructure_timeout_seconds,
            )
        except Exception:
            return False
        del reader
        writer.close()
        await writer.wait_closed()
        return True

    def _mark_http_unavailable(self) -> None:
        """Update only public diagnostics after the local HTTP socket disappears."""

        servers = dict(self.diagnostics.servers)
        current = servers.get(TRAVEL_SERVER_NAME)
        if current is not None:
            servers[TRAVEL_SERVER_NAME] = current.model_copy(update={"ready": False})
        self.diagnostics = self.diagnostics.model_copy(
            update={
                "ready": False,
                "servers": servers,
                "last_error_type": "mcp_transport_unavailable",
            }
        )


async def create_mcp_runtime(settings: Settings) -> MCPRuntime:
    """Create a stateless client, discover once, and retain no open session."""

    client = build_mcp_client(settings)
    registry, diagnostics = await _discover(client, settings)
    invoker = MCPToolInvoker(
        registry=registry,
        timeout_seconds=settings.mcp_tool_timeout_seconds,
        max_retries=settings.mcp_max_retries,
    )
    backend = MCPTravelSearchBackend(invoker)
    return MCPRuntime(
        settings=settings,
        client=client,
        registry=registry,
        diagnostics=diagnostics,
        invoker=invoker,
        backend=backend,
        _next_refresh_time=time.monotonic() + _REFRESH_COOLDOWN_SECONDS,
    )
