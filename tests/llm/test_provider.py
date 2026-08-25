"""Offline Qwen SDK adapter tests for JSON, retries, and safe errors."""

import asyncio
import json
from typing import cast

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from prometheus_client import generate_latest
from pydantic import ValidationError

from app.llm.errors import LLMError
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.models import (
    FlightCandidate,
    HotelCandidate,
    PlannerPromptInput,
    QwenPlanDecision,
    RevisionPromptSnapshot,
    TripPromptSnapshot,
)
from app.llm.qwen import QwenStructuredLLMProvider
from app.observability.metrics import MetricsRuntime
from tests.llm.helpers import FakeAsyncOpenAI, completion


def prompt_input() -> PlannerPromptInput:
    """Return the smallest valid Planner prompt DTO."""

    return PlannerPromptInput(
        trip=TripPromptSnapshot(
            origin="Shanghai",
            destination="Tokyo",
            start_date="2027-04-10",
            end_date="2027-04-10",
            budget="10000.00",
            currency="CNY",
            travelers=1,
        ),
        flights=[
            FlightCandidate(
                candidate_id=f"flight_{'a' * 24}",
                flight_number="MK1",
                airline="Mock",
                departure_time="2027-04-10T08:00:00",
                arrival_time="2027-04-10T10:00:00",
                duration_minutes=120,
                price="100.00",
                currency="CNY",
            )
        ],
        hotels=[
            HotelCandidate(
                candidate_id=f"hotel_{'b' * 24}",
                name="Mock Hotel",
                rating=4.5,
                price_per_night="200.00",
                currency="CNY",
                distance_to_center_km=1,
            )
        ],
        revision=RevisionPromptSnapshot(),
    )


def decision_payload() -> dict[str, object]:
    """Return valid JSON data rather than a trusted domain entity."""

    return {
        "selected_flight_id": f"flight_{'a' * 24}",
        "selected_hotel_id": f"hotel_{'b' * 24}",
        "daily_attraction_ids": [{"day_number": 1, "attraction_ids": []}],
        "planning_notes": "Known candidates only.",
        "preference_alignment": "No preferences supplied.",
    }


def provider(
    client: FakeAsyncOpenAI,
    *,
    max_retries: int = 1,
    metrics: MetricsRuntime | None = None,
    sleeps: list[float] | None = None,
) -> QwenStructuredLLMProvider:
    """Build the real adapter around a no-network SDK-shaped client."""

    async def sleeper(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return QwenStructuredLLMProvider(
        client=cast(AsyncOpenAI, client),
        model="qwen-plus",
        temperature=0.2,
        max_retries=max_retries,
        max_completion_tokens=2048,
        metrics=metrics,
        sleeper=sleeper,
    )


@pytest.mark.asyncio
async def test_valid_json_uses_required_model_studio_parameters_and_real_usage() -> None:
    client = FakeAsyncOpenAI([completion(decision_payload())])

    result = await provider(client).plan(prompt_input())

    assert isinstance(result.value, QwenPlanDecision)
    assert result.model == "qwen-plus-test"
    assert (result.input_tokens, result.output_tokens) == (7, 3)
    call = client.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"enable_thinking": False}
    assert call["temperature"] == 0.2
    assert call["max_completion_tokens"] == 2048


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("not-json", "llm_invalid_json"),
        ({"unexpected": "shape"}, "llm_schema_validation_failed"),
    ],
)
async def test_invalid_provider_output_maps_to_stable_error(
    content: dict[str, object] | str,
    code: str,
) -> None:
    client = FakeAsyncOpenAI([completion(content)])

    with pytest.raises(LLMError, match=code) as captured:
        await provider(client).plan(prompt_input())

    assert str(captured.value) == code
    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_numeric_strings_are_not_coerced_across_the_output_schema() -> None:
    payload = decision_payload()
    payload["daily_attraction_ids"] = [{"day_number": "1", "attraction_ids": []}]
    client = FakeAsyncOpenAI([completion(payload)])

    with pytest.raises(LLMError, match="llm_schema_validation_failed"):
        await provider(client).plan(prompt_input())

    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_keys_and_nonstandard_constants_are_invalid_json() -> None:
    payload = decision_payload()
    valid_json = json.dumps(payload)
    selected_key = f'"selected_flight_id": "{payload["selected_flight_id"]}"'
    duplicate_key = f"{selected_key}, {selected_key}"
    duplicate_json = valid_json.replace(selected_key, duplicate_key, 1)
    nonstandard_json = valid_json.replace('"Known candidates only."', "NaN", 1)

    for content in (duplicate_json, nonstandard_json):
        client = FakeAsyncOpenAI([completion(content)])
        with pytest.raises(LLMError, match="llm_invalid_json"):
            await provider(client).plan(prompt_input())
        assert len(client.completions.calls) == 1


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def _response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code, request=_request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (APITimeoutError(_request()), "llm_timeout"),
        (
            RateLimitError("private rate detail", response=_response(429), body=None),
            "llm_rate_limited",
        ),
        (
            APIConnectionError(message="private transport detail", request=_request()),
            "llm_transport_error",
        ),
    ],
)
async def test_retryable_sdk_errors_retry_once_then_succeed(
    error: BaseException,
    code: str,
) -> None:
    client = FakeAsyncOpenAI([error, completion(decision_payload())])
    sleeps: list[float] = []

    result = await provider(client, max_retries=1, sleeps=sleeps).plan(prompt_input())

    assert isinstance(result.value, QwenPlanDecision)
    assert len(client.completions.calls) == 2
    assert sleeps == [0.1]
    assert code.startswith("llm_")


@pytest.mark.asyncio
async def test_retry_is_strictly_bounded() -> None:
    client = FakeAsyncOpenAI(
        [
            APITimeoutError(_request()),
            APITimeoutError(_request()),
            completion(decision_payload()),
        ]
    )

    with pytest.raises(LLMError, match="llm_timeout"):
        await provider(client, max_retries=1).plan(prompt_input())

    assert len(client.completions.calls) == 2


@pytest.mark.asyncio
async def test_authentication_failure_is_never_retried_or_leaked() -> None:
    private = "not-a-real-key"
    error = AuthenticationError(
        f"invalid key {private}",
        response=_response(401),
        body=None,
    )
    client = FakeAsyncOpenAI([error, completion(decision_payload())])

    with pytest.raises(LLMError, match="llm_authentication_failed") as captured:
        await provider(client, max_retries=2).plan(prompt_input())

    assert len(client.completions.calls) == 1
    assert private not in str(captured.value)
    assert "invalid key" not in str(captured.value)


@pytest.mark.asyncio
async def test_unknown_exception_becomes_safe_provider_error() -> None:
    private = "private SDK traceback and token"
    client = FakeAsyncOpenAI([RuntimeError(private)])

    with pytest.raises(LLMError, match="llm_provider_error") as captured:
        await provider(client, max_retries=0).plan(prompt_input())

    assert private not in str(captured.value)


@pytest.mark.asyncio
async def test_cancellation_propagates_without_business_error_or_metric() -> None:
    metrics = MetricsRuntime.create()
    client = FakeAsyncOpenAI([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await provider(client, max_retries=2, metrics=metrics).plan(prompt_input())

    exposition = generate_latest(metrics.registry).decode("utf-8")
    assert "travel_planner_llm_requests_total{" not in exposition
    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_metrics_use_bounded_labels_and_only_real_usage() -> None:
    metrics = MetricsRuntime.create()
    client = FakeAsyncOpenAI(
        [completion(decision_payload(), prompt_tokens=11, completion_tokens=5)]
    )

    await provider(client, metrics=metrics).plan(prompt_input())
    assert client.completions.calls
    exposition = generate_latest(metrics.registry).decode("utf-8")
    assert 'travel_planner_llm_requests_total{role="planner",status="success"} 1.0' in exposition
    assert 'travel_planner_llm_tokens_total{direction="input"} 11.0' in exposition
    assert 'travel_planner_llm_tokens_total{direction="output"} 5.0' in exposition
    assert "not-a-real" not in exposition


@pytest.mark.asyncio
async def test_fake_provider_performs_no_network_and_is_schema_strict() -> None:
    fake = FakeStructuredLLMProvider()

    result = await fake.plan(prompt_input())

    assert isinstance(result.value, QwenPlanDecision)
    assert len(fake.plan_inputs) == 1
    with pytest.raises(ValidationError):
        QwenPlanDecision.model_validate({**decision_payload(), "price": "invented"})
