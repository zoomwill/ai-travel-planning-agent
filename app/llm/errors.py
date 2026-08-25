"""Stable LLM failures that never expose SDK exception details."""

from typing import Literal, TypeAlias

LLMErrorCode: TypeAlias = Literal[
    "llm_not_configured",
    "llm_invalid_base_url",
    "llm_timeout",
    "llm_rate_limited",
    "llm_authentication_failed",
    "llm_transport_error",
    "llm_invalid_json",
    "llm_schema_validation_failed",
    "llm_grounding_violation",
    "llm_provider_error",
]


class LLMError(RuntimeError):
    """Carry one public error code while retaining no private exception text."""

    def __init__(self, code: LLMErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)
