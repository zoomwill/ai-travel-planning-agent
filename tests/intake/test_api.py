"""Offline HTTP tests for conversation, confirmation, reset, and P12 SSE reuse."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore
from prometheus_client.parser import text_string_to_metric_families

from app.api.routes.conversation import (
    _PreparedConfirmationStream,
    stream_confirmed_conversation,
)
from app.api.routes.persistence import _PreparedPlanStream
from app.core.config import Settings
from app.core.resources import AppResources
from app.intake.models import TripRequirementPatch
from app.intake.service import ConversationIntakeService
from app.llm.diagnostics import LLMRuntimeDiagnostics
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.models import QwenTripRequirementExtraction
from app.llm.runtime import LLMRuntime
from app.main import create_app
from tests.api.test_streaming import parse_sse
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.streaming.test_service import BlockingGraph, FakeGraph, final_chunk, make_stream


def extraction(**values: object) -> QwenTripRequirementExtraction:
    """Create one strict fake extraction result."""

    return QwenTripRequirementExtraction(patch=TripRequirementPatch.model_validate(values))


def complete_extraction(**updates: object) -> QwenTripRequirementExtraction:
    """Create a complete one-day request suitable for deterministic providers."""

    values: dict[str, object] = {
        "origin": "Shanghai",
        "destination": "Tokyo",
        "start_date": "2026-09-01",
        "duration_days": 3,
        "budget": 10000,
        "currency": "CNY",
        "travelers": 1,
        "preferences_add": ["photography"],
    }
    values.update(updates)
    return extraction(**values)


@contextmanager
def conversation_client(
    scripted: list[QwenTripRequirementExtraction],
) -> Iterator[tuple[TestClient, FakeStructuredLLMProvider, FastAPI]]:
    """Run the app with one fake intake provider and in-memory persistence."""

    settings = Settings(_env_file=None, sse_heartbeat_seconds=0.01)
    provider = FakeStructuredLLMProvider(intake_extractions=scripted)
    runtime = LLMRuntime(
        provider=provider,
        diagnostics=LLMRuntimeDiagnostics(
            reasoning_mode="qwen",
            provider="qwen",
            configured=True,
            model="fake-qwen",
            base_url_host_class="china-beijing",
            fallback_enabled=False,
        ),
    )
    fakes = make_resource_fakes(settings)
    fakes.resources.llm_runtime = runtime

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(
            lambda _: ["Local static Tokyo photography context."]
        ),
    )
    with TestClient(application) as client:
        yield client, provider, application


def post_message(
    client: TestClient,
    *,
    thread_id: str = "intake-thread",
    user_id: str = "intake-user",
    message: str = "Trip details",
    start_new_trip: bool = False,
) -> object:
    """Send one public message request."""

    return client.post(
        f"/api/v1/agents/threads/{thread_id}/conversation/messages",
        json={
            "user_id": user_id,
            "message": message,
            "start_new_trip": start_new_trip,
        },
    )


def test_message_get_and_user_isolation_are_strict() -> None:
    with conversation_client([extraction(destination="Tokyo")]) as (client, _, _):
        message = post_message(client)
        own = client.get("/api/v1/agents/threads/intake-thread/conversation?user_id=intake-user")
        other = client.get("/api/v1/agents/threads/intake-thread/conversation?user_id=other-user")

    assert message.status_code == 200
    assert message.json()["status"] == "collecting"
    assert message.json()["draft"]["destination"] == "Tokyo"
    assert own.status_code == 200 and own.json() == message.json()
    assert other.status_code == 404
    assert "current_draft" not in message.text


def test_complete_message_does_not_run_graph_until_nonstream_confirmation() -> None:
    with conversation_client([complete_extraction()]) as (client, _, _):
        ready = post_message(client)
        before = client.get("/metrics").text
        confirmed = client.post(
            "/api/v1/agents/threads/intake-thread/conversation/confirm",
            json={
                "user_id": "intake-user",
                "draft_fingerprint": ready.json()["draft_fingerprint"],
                "remember_preferences": ["Quiet neighborhoods"],
            },
        )
        after = client.get("/metrics").text
        conversation = client.get(
            "/api/v1/agents/threads/intake-thread/conversation?user_id=intake-user"
        )
        memories = client.get("/api/v1/users/intake-user/preferences")

    assert ready.status_code == 200
    assert ready.json()["status"] == "awaiting_confirmation"
    assert "travel_planner_graph_runs_total{" not in before
    assert confirmed.status_code == 200
    assert confirmed.json()["travel_plan"]["requirements"]["destination"] == "Tokyo"
    assert 'travel_planner_graph_runs_total{backend="direct",status="success"} 1.0' in after
    assert conversation.json()["status"] == "planned"
    assert conversation.json()["plan_available"] is True
    assert [item["value"] for item in memories.json()] == ["Quiet neighborhoods"]


def test_stale_fingerprint_never_runs_graph() -> None:
    with conversation_client([complete_extraction(), extraction(budget=2500)]) as (client, _, _):
        first = post_message(client)
        second = post_message(client, message="Actually make the budget 2500")
        stale = client.post(
            "/api/v1/agents/threads/intake-thread/conversation/confirm",
            json={
                "user_id": "intake-user",
                "draft_fingerprint": first.json()["draft_fingerprint"],
            },
        )
        metrics = client.get("/metrics").text

    assert first.json()["draft_fingerprint"] != second.json()["draft_fingerprint"]
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_draft_fingerprint"
    assert "travel_planner_graph_runs_total{" not in metrics


def test_stream_confirmation_reuses_p12_events_and_marks_planned() -> None:
    with conversation_client([complete_extraction()]) as (client, _, _):
        ready = post_message(client, thread_id="stream-intake")
        response = client.post(
            "/api/v1/agents/threads/stream-intake/conversation/confirm/stream",
            json={
                "user_id": "intake-user",
                "draft_fingerprint": ready.json()["draft_fingerprint"],
                "remember_preferences": [],
            },
        )
        events, comments = parse_sse(response.text)
        state = client.get("/api/v1/agents/threads/stream-intake/conversation?user_id=intake-user")

    event_types = [event["event_type"] for event in events]
    search_kinds = {
        event["data"]["search_kind"] for event in events if event["event_type"] == "search_started"
    }
    assert response.status_code == 200
    assert event_types[0] == "run_started"
    assert search_kinds == {"flights", "hotels", "attractions", "weather", "route"}
    assert "review_completed" in event_types
    assert event_types[-1] == "plan_completed"
    assert event_types.count("plan_completed") == 1
    assert "error" not in event_types
    assert [event["event_id"] for event in events] == list(range(1, len(events) + 1))
    assert set(comments).issubset({"ping"})
    assert state.json()["status"] == "planned"


def test_reset_and_start_new_trip_do_not_delete_existing_graph_checkpoint() -> None:
    with conversation_client([complete_extraction(), extraction(destination="Paris")]) as (
        client,
        _,
        _,
    ):
        ready = post_message(client)
        client.post(
            "/api/v1/agents/threads/intake-thread/conversation/confirm",
            json={
                "user_id": "intake-user",
                "draft_fingerprint": ready.json()["draft_fingerprint"],
            },
        )
        blocked = post_message(client, message="Change to Paris")
        reset = client.post(
            "/api/v1/agents/threads/intake-thread/conversation/reset",
            json={"user_id": "intake-user"},
        )
        graph_state = client.get("/api/v1/agents/threads/intake-thread/state")
        new_trip = post_message(
            client,
            message="A new Paris trip",
            start_new_trip=True,
        )

    assert blocked.status_code == 409
    assert reset.status_code == 200
    assert reset.json()["draft"] == {
        "origin": None,
        "destination": None,
        "start_date": None,
        "end_date": None,
        "duration_days": None,
        "budget": None,
        "currency": None,
        "travelers": None,
        "preferences": [],
    }
    assert graph_state.status_code == 200 and graph_state.json()["status"] == "complete"
    assert new_trip.status_code == 200
    assert new_trip.json()["draft"]["destination"] == "Paris"


def test_default_deterministic_runtime_returns_safe_503_but_old_plan_still_works() -> None:
    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    app = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(app) as client:
        intake = post_message(client)
        old_plan = client.post(
            "/api/v1/agents/threads/old-plan/plans",
            json={
                "user_id": "intake-user",
                "requirements": {
                    "origin": "Shanghai",
                    "destination": "Tokyo",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-03",
                    "budget": "10000",
                    "currency": "CNY",
                    "travelers": 1,
                    "preferences": [],
                },
            },
        )

    assert intake.status_code == 503
    assert intake.json()["detail"]["code"] == "conversational_intake_requires_llm"
    assert old_plan.status_code == 200


def test_metrics_exposition_remains_parseable() -> None:
    with conversation_client([extraction(destination="Tokyo")]) as (client, _, _):
        post_message(client)
        families = list(text_string_to_metric_families(client.get("/metrics").text))

    names = {family.name for family in families}
    assert "travel_planner_intake_turns" in names
    assert "travel_planner_intake_turn_duration_seconds" in names


async def _planning_intake() -> tuple[ConversationIntakeService, str]:
    """Create one in-memory intake already transitioned to planning."""

    provider = FakeStructuredLLMProvider(intake_extractions=[complete_extraction()])
    service = ConversationIntakeService(
        store=InMemoryStore(),
        provider=provider,
        clock=lambda: datetime(2026, 8, 26, 12, tzinfo=UTC),
        current_date=lambda: date(2026, 8, 26),
    )
    ready = await service.process_message(
        user_id="intake-user",
        thread_id="stream-intake",
        message="Complete trip",
    )
    await service.begin_confirmation(
        user_id="intake-user",
        thread_id="stream-intake",
        fingerprint=ready.draft_fingerprint,
    )
    return service, ready.draft_fingerprint


@pytest.mark.asyncio
async def test_confirm_stream_disconnect_restores_retryable_intake() -> None:
    """Closing the wrapper cancels P12 and never marks the conversation planned."""

    service, fingerprint = await _planning_intake()
    graph = BlockingGraph()
    generator = stream_confirmed_conversation(
        _PreparedConfirmationStream(
            prepared=_PreparedPlanStream(stream=make_stream(graph, heartbeat=60)),
            service=service,
            user_id="intake-user",
            thread_id="stream-intake",
            fingerprint=fingerprint,
        )
    )

    first = await anext(generator)
    assert first.event == "run_started"
    await asyncio.wait_for(graph.started.wait(), timeout=1)
    await generator.aclose()
    state = await service.get_state(user_id="intake-user", thread_id="stream-intake")

    assert state.status == "awaiting_confirmation"
    assert state.plan_available is False
    assert graph.astream_calls == 1


@pytest.mark.asyncio
async def test_confirm_stream_error_preserves_draft_and_never_marks_planned() -> None:
    """A P12 error terminal is still exactly one safe error and remains retryable."""

    service, fingerprint = await _planning_intake()
    graph = FakeGraph([], error=RuntimeError("private traceback with Bearer token"))
    generator = stream_confirmed_conversation(
        _PreparedConfirmationStream(
            prepared=_PreparedPlanStream(stream=make_stream(graph)),
            service=service,
            user_id="intake-user",
            thread_id="stream-intake",
            fingerprint=fingerprint,
        )
    )
    events = [event async for event in generator]
    state = await service.get_state(user_id="intake-user", thread_id="stream-intake")

    assert [event.event for event in events].count("error") == 1
    assert "plan_completed" not in [event.event for event in events]
    assert state.status == "awaiting_confirmation"
    assert state.plan_available is False


@pytest.mark.asyncio
async def test_stream_marks_planned_only_after_downstream_resumes_past_terminal() -> None:
    """Match P12's disconnect-safe terminal commit boundary."""

    service, fingerprint = await _planning_intake()
    generator = stream_confirmed_conversation(
        _PreparedConfirmationStream(
            prepared=_PreparedPlanStream(stream=make_stream(FakeGraph([final_chunk()]))),
            service=service,
            user_id="intake-user",
            thread_id="stream-intake",
            fingerprint=fingerprint,
        )
    )
    terminal = None
    while terminal is None or terminal.event != "plan_completed":
        terminal = await anext(generator)

    before_resume = await service.get_state(user_id="intake-user", thread_id="stream-intake")
    assert before_resume.status == "planning"

    with pytest.raises(StopAsyncIteration):
        await anext(generator)
    after_resume = await service.get_state(user_id="intake-user", thread_id="stream-intake")
    assert after_resume.status == "planned"
