"""Application-lifespan ownership for the optional Qwen provider."""

from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.configuration import validate_qwen_base_url
from app.llm.diagnostics import LLMRuntimeDiagnostics
from app.llm.errors import LLMError, LLMErrorCode
from app.llm.protocol import StructuredLLMProvider
from app.llm.qwen import QwenStructuredLLMProvider
from app.observability.metrics import MetricsRuntime


@dataclass(slots=True)
class LLMRuntime:
    """Provider plus safe diagnostics owned by one FastAPI lifespan."""

    provider: StructuredLLMProvider | None
    diagnostics: LLMRuntimeDiagnostics

    async def aclose(self) -> None:
        """Close the provider only when qwen mode created one."""

        if self.provider is not None:
            await self.provider.aclose()


def create_llm_runtime(
    settings: Settings,
    metrics: MetricsRuntime | None = None,
) -> LLMRuntime:
    """Create no client in deterministic mode and one shared client in qwen mode."""

    host_class = validate_qwen_base_url(settings.qwen_base_url)
    if settings.agent_reasoning_mode == "deterministic":
        return LLMRuntime(
            provider=None,
            diagnostics=_diagnostics(settings, host_class, configured=False),
        )
    if not settings.qwen_is_configured:
        return LLMRuntime(
            provider=None,
            diagnostics=_diagnostics(
                settings,
                host_class,
                configured=False,
                initialization_error="llm_not_configured",
            ),
        )
    try:
        client = AsyncOpenAI(
            api_key=settings.qwen_api_key.get_secret_value(),
            base_url=settings.qwen_base_url,
            timeout=settings.qwen_timeout_seconds,
            max_retries=0,
        )
        provider = QwenStructuredLLMProvider(
            client=client,
            model=settings.qwen_model,
            temperature=settings.qwen_temperature,
            max_retries=settings.qwen_max_retries,
            max_completion_tokens=settings.qwen_max_completion_tokens,
            metrics=metrics,
        )
    except Exception:
        return LLMRuntime(
            provider=None,
            diagnostics=_diagnostics(
                settings,
                host_class,
                configured=False,
                initialization_error="llm_provider_error",
            ),
        )
    return LLMRuntime(
        provider=provider,
        diagnostics=_diagnostics(settings, host_class, configured=True),
    )


def require_qwen_provider(runtime: LLMRuntime) -> StructuredLLMProvider:
    """Return the configured provider or one stable setup failure."""

    if runtime.provider is None:
        code = runtime.diagnostics.initialization_error or "llm_not_configured"
        raise LLMError(code)
    return runtime.provider


def _diagnostics(
    settings: Settings,
    host_class: str,
    *,
    configured: bool,
    initialization_error: LLMErrorCode | None = None,
) -> LLMRuntimeDiagnostics:
    """Build safe diagnostics with fields mypy can verify individually."""

    return LLMRuntimeDiagnostics(
        reasoning_mode=settings.agent_reasoning_mode,
        provider="qwen" if settings.agent_reasoning_mode == "qwen" else "none",
        configured=configured,
        model=settings.qwen_model,
        base_url_host_class=host_class,
        fallback_enabled=settings.qwen_allow_deterministic_fallback,
        initialization_error=initialization_error,
    )
