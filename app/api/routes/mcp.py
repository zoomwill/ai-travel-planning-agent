"""Safe local diagnostics for the Phase P11 MCP tool layer."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_resources
from app.core.resources import AppResources
from app.mcp_tools.diagnostics import (
    MCPDiagnostics,
    direct_mode_diagnostics,
    unavailable_mcp_diagnostics,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/status", response_model=MCPDiagnostics)
async def mcp_status(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> MCPDiagnostics:
    """Return discovery names and readiness without commands, URLs, or secrets."""

    if resources.settings.travel_search_backend_mode == "direct":
        return direct_mode_diagnostics()
    if resources.mcp_runtime is None:
        return unavailable_mcp_diagnostics()
    await resources.mcp_runtime.is_ready()
    return resources.mcp_runtime.diagnostics
