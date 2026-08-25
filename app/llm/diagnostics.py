"""Safe public runtime diagnostics and LLM observation helpers."""

from dataclasses import dataclass
from typing import Literal

from app.llm.errors import LLMErrorCode
from app.llm.models import LLMRole
from app.observability.logging import log_event
from app.observability.metrics import MetricsRuntime


@dataclass(frozen=True, slots=True)
class LLMRuntimeDiagnostics:
    """Configuration facts safe for readiness and status responses."""

    reasoning_mode: Literal["deterministic", "qwen"]
    provider: Literal["none", "qwen"]
    configured: bool
    model: str
    base_url_host_class: str
    fallback_enabled: bool
    initialization_error: LLMErrorCode | None = None


def record_deterministic_fallback(
    metrics: MetricsRuntime | None,
    role: LLMRole,
    error_code: LLMErrorCode,
) -> None:
    """Make an explicitly configured local fallback observable without private data."""

    if metrics is not None:
        metrics.llm_requests.labels(role=role, status="fallback").inc()
        metrics.llm_duration.labels(role=role, status="fallback").observe(0)
    log_event(
        "llm_deterministic_fallback",
        "An explicitly enabled deterministic LLM fallback was used.",
        component="llm",
        role=role,
        outcome="fallback",
        error_code=error_code,
        fallback=True,
    )
