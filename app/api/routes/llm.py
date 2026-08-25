"""Read-only status for the optional Qwen reasoning runtime."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_resources
from app.core.resources import AppResources
from app.schemas.llm import LLMStatusResponse

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


@router.get("/status", response_model=LLMStatusResponse)
async def llm_status(
    resources: Annotated[AppResources, Depends(get_app_resources)],
) -> LLMStatusResponse:
    """Return cached configuration diagnostics without a paid provider call."""

    runtime = resources.llm_runtime
    if runtime is None:
        return LLMStatusResponse(
            reasoning_mode=resources.settings.agent_reasoning_mode,
            provider="none",
            configured=False,
            model=resources.settings.qwen_model,
            base_url_region_or_host_class="uninitialized",
            fallback_enabled=resources.settings.qwen_allow_deterministic_fallback,
        )
    diagnostics = runtime.diagnostics
    return LLMStatusResponse(
        reasoning_mode=diagnostics.reasoning_mode,
        provider=diagnostics.provider,
        configured=diagnostics.configured,
        model=diagnostics.model,
        base_url_region_or_host_class=diagnostics.base_url_host_class,
        fallback_enabled=diagnostics.fallback_enabled,
    )
