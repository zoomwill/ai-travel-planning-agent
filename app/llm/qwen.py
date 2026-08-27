"""Alibaba Cloud Model Studio adapter using its OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from pydantic import ValidationError

from app.llm.errors import LLMError
from app.llm.models import (
    IntakePromptInput,
    LLMModel,
    LLMRole,
    PlannerPromptInput,
    QwenPlanDecision,
    QwenPlanReview,
    QwenSmokeResponse,
    QwenTripRequirementExtraction,
    ReviewerPromptInput,
    StructuredLLMResult,
)
from app.llm.prompts import intake_messages, planner_messages, reviewer_messages, smoke_messages
from app.observability.logging import log_event
from app.observability.metrics import LLM_ROLES, LLM_STATUSES, MetricsRuntime, normalize_label

OutputT = TypeVar("OutputT", bound=LLMModel)
Sleeper = Callable[[float], Awaitable[None]]


class QwenStructuredLLMProvider:
    """Reuse one async SDK client for bounded, schema-validated Qwen calls."""

    def __init__(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        temperature: float,
        max_retries: int,
        max_completion_tokens: int,
        metrics: MetricsRuntime | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._max_completion_tokens = max_completion_tokens
        self._metrics = metrics
        self._sleeper = sleeper

    async def plan(
        self,
        prompt_input: PlannerPromptInput,
    ) -> StructuredLLMResult[QwenPlanDecision]:
        """Request one grounded candidate decision."""

        return await self._generate(
            role="planner",
            messages=planner_messages(prompt_input),
            output_model=QwenPlanDecision,
        )

    async def review(
        self,
        prompt_input: ReviewerPromptInput,
    ) -> StructuredLLMResult[QwenPlanReview]:
        """Request one semantic assessment without a loop decision."""

        return await self._generate(
            role="reviewer",
            messages=reviewer_messages(prompt_input),
            output_model=QwenPlanReview,
        )

    async def extract_trip_requirements(
        self,
        prompt_input: IntakePromptInput,
    ) -> StructuredLLMResult[QwenTripRequirementExtraction]:
        """Extract one bounded semantic patch from the current redacted message."""

        return await self._generate(
            role="intake",
            messages=intake_messages(prompt_input),
            output_model=QwenTripRequirementExtraction,
        )

    async def smoke_test(self) -> StructuredLLMResult[QwenSmokeResponse]:
        """Issue the explicit minimal paid Model Studio check."""

        return await self._generate(
            role="planner",
            messages=smoke_messages(),
            output_model=QwenSmokeResponse,
        )

    async def aclose(self) -> None:
        """Close the application-owned asynchronous HTTP client."""

        await self._client.close()

    async def _generate(
        self,
        *,
        role: LLMRole,
        messages: list[dict[str, str]],
        output_model: type[OutputT],
    ) -> StructuredLLMResult[OutputT]:
        """Perform bounded retries, then parse JSON and validate the exact schema."""

        started = time.monotonic()
        status = "error"
        cancelled = False
        input_tokens: int | None = None
        output_tokens: int | None = None
        try:
            response: ChatCompletion | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=cast(list[ChatCompletionMessageParam], messages),
                        response_format={"type": "json_object"},
                        temperature=self._temperature,
                        max_completion_tokens=self._max_completion_tokens,
                        extra_body={"enable_thinking": False},
                    )
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                except Exception as exc:
                    error = _map_sdk_error(exc)
                    if not error.retryable or attempt >= self._max_retries:
                        raise error from None
                    await self._sleeper(0.1 * (attempt + 1))
            if response is None:
                raise LLMError("llm_provider_error")
            input_tokens, output_tokens = _usage(response)
            value = _validated_content(response, output_model)
            status = "success"
            return StructuredLLMResult(
                value=value,
                model=response.model or self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except LLMError as exc:
            status = _metric_status(exc)
            raise
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            duration = max(0.0, time.monotonic() - started)
            if self._metrics is not None and not cancelled:
                labels = {
                    "role": normalize_label(role, LLM_ROLES),
                    "status": normalize_label(status, LLM_STATUSES),
                }
                self._metrics.llm_requests.labels(**labels).inc()
                self._metrics.llm_duration.labels(**labels).observe(duration)
                if input_tokens is not None:
                    self._metrics.llm_tokens.labels(direction="input").inc(input_tokens)
                if output_tokens is not None:
                    self._metrics.llm_tokens.labels(direction="output").inc(output_tokens)
            if not cancelled:
                log_event(
                    "llm_request_completed",
                    "A structured LLM request completed.",
                    component="llm",
                    role=role,
                    model=self._model,
                    duration_ms=round(duration * 1000, 3),
                    outcome=status,
                    input_token_count=input_tokens,
                    output_token_count=output_tokens,
                )


def _validated_content(response: ChatCompletion, output_model: type[OutputT]) -> OutputT:
    """Parse exactly one JSON object without regex or unsafe evaluation."""

    if not response.choices:
        raise LLMError("llm_invalid_json")
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise LLMError("llm_invalid_json")
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, ValueError):
        raise LLMError("llm_invalid_json") from None
    try:
        return output_model.model_validate(payload)
    except ValidationError:
        raise LLMError("llm_schema_validation_failed") from None


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys instead of silently accepting the final value."""

    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_nonstandard_json_constant(value: str) -> object:
    """Reject NaN and infinities, which are not valid JSON values."""

    raise ValueError(f"non-standard JSON constant: {value}")


def _usage(response: ChatCompletion) -> tuple[int | None, int | None]:
    """Read only real SDK usage values and never estimate missing tokens."""

    usage = response.usage
    if usage is None:
        return None, None
    return usage.prompt_tokens, usage.completion_tokens


def _map_sdk_error(exc: BaseException) -> LLMError:
    """Replace every SDK exception with a stable non-secret code."""

    if isinstance(exc, APITimeoutError):
        return LLMError("llm_timeout", retryable=True)
    if isinstance(exc, RateLimitError):
        return LLMError("llm_rate_limited", retryable=True)
    if isinstance(exc, AuthenticationError):
        return LLMError("llm_authentication_failed")
    if isinstance(exc, APIConnectionError):
        return LLMError("llm_transport_error", retryable=True)
    if isinstance(exc, APIStatusError):
        return LLMError("llm_provider_error", retryable=exc.status_code >= 500)
    return LLMError("llm_provider_error")


def _metric_status(error: LLMError) -> str:
    """Collapse stable errors into the documented low-cardinality statuses."""

    if error.code == "llm_timeout":
        return "timeout"
    if error.code in {"llm_invalid_json", "llm_schema_validation_failed"}:
        return "invalid_response"
    return "error"
