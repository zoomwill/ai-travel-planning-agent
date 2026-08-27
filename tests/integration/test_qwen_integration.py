"""Explicit low-volume real Qwen intake, planning, review, and SSE invariant test."""

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.main import create_app
from app.services.planning_service import MOCK_PLANNING_PROVIDERS
from tests.api.test_streaming import parse_sse

pytestmark = [
    pytest.mark.llm_integration,
    pytest.mark.skipif(
        os.getenv("RUN_LLM_INTEGRATION_TESTS") != "1",
        reason="set RUN_LLM_INTEGRATION_TESTS=1 for the paid Qwen test",
    ),
]


async def _cleanup(settings: Settings, thread_id: str, user_id: str) -> None:
    """Delete only UUID-scoped checkpoint, intake, and memory test data."""

    uri = settings.langgraph_postgres_uri.get_secret_value()
    async with AsyncPostgresSaver.from_conn_string(
        uri,
        serde=create_strict_serializer(),
    ) as saver:
        await saver.adelete_thread(thread_id)
    async with AsyncPostgresStore.from_conn_string(uri) as store:
        await store.adelete((user_id, "trip_intake"), thread_id)
        memories = await store.asearch((user_id, "travel_preferences"), limit=100)
        for memory in memories:
            await store.adelete((user_id, "travel_preferences"), memory.key)


def test_real_qwen_conversation_confirmation_and_grounded_stream() -> None:
    """Pay for one full P15 path and assert facts rather than free-text wording."""

    loaded = Settings()
    if not loaded.qwen_is_configured:
        pytest.skip("QWEN_API_KEY or DASHSCOPE_API_KEY is unavailable")
    settings = loaded.model_copy(
        update={
            "agent_reasoning_mode": "qwen",
            "qwen_allow_deterministic_fallback": False,
            "travel_search_backend_mode": "direct",
        }
    )
    thread_id = f"p15-qwen-{uuid.uuid4().hex}"
    user_id = f"p15-user-{uuid.uuid4().hex}"
    application = create_app(settings=settings)

    try:
        with TestClient(application) as client:
            first = client.post(
                f"/api/v1/agents/threads/{thread_id}/conversation/messages",
                json={
                    "user_id": user_id,
                    "message": (
                        "I want to travel from Shanghai to Tokyo starting 2027-04-10 "
                        "for three days."
                    ),
                },
            )
            assert first.status_code == 200
            assert first.json()["status"] == "collecting"

            second = client.post(
                f"/api/v1/agents/threads/{thread_id}/conversation/messages",
                json={
                    "user_id": user_id,
                    "message": (
                        "One traveler, total budget 12000 CNY. For this trip I prefer "
                        "museums and quiet walks."
                    ),
                },
            )
            assert second.status_code == 200
            intake = second.json()
            assert intake["status"] == "awaiting_confirmation"
            assert intake["can_confirm"] is True
            assert intake["draft"]["origin"] == "Shanghai"
            assert intake["draft"]["destination"] == "Tokyo"
            assert intake["draft"]["start_date"] == "2027-04-10"
            assert intake["draft"]["end_date"] == "2027-04-12"
            assert intake["draft"]["travelers"] == 1
            assert "travel_planner_graph_runs_total{" not in client.get("/metrics").text

            response = client.post(
                f"/api/v1/agents/threads/{thread_id}/conversation/confirm/stream",
                json={
                    "user_id": user_id,
                    "draft_fingerprint": intake["draft_fingerprint"],
                    "remember_preferences": ["quiet hotels"],
                },
            )
            assert response.status_code == 200
            events, _ = parse_sse(response.text)
            event_types = [event["event_type"] for event in events]
            assert event_types[0] == "run_started"
            assert event_types[-1] == "plan_completed"
            assert event_types.count("plan_completed") == 1
            assert "error" not in event_types
            starts = {
                event["data"]["search_kind"]
                for event in events
                if event["event_type"] == "search_started"
            }
            assert starts == {"flights", "hotels", "attractions", "weather", "route"}

            plan = TravelPlan.model_validate(events[-1]["data"]["travel_plan"])
            requirements = plan.requirements
            assert plan.flight in MOCK_PLANNING_PROVIDERS.search_flights(requirements)
            assert plan.hotel in MOCK_PLANNING_PROVIDERS.search_hotels(requirements)
            known_attraction_names = {
                item.name for item in MOCK_PLANNING_PROVIDERS.search_attractions(requirements)
            }
            selected_visits = [
                activity.removeprefix("Visit ").split(" (", maxsplit=1)[0]
                for day in plan.daily_itinerary
                for activity in day.activities
                if activity.startswith("Visit ")
            ]
            assert set(selected_visits) <= known_attraction_names

            state = client.get(f"/api/v1/agents/threads/{thread_id}/state")
            conversation = client.get(
                f"/api/v1/agents/threads/{thread_id}/conversation?user_id={user_id}"
            )
            metrics = client.get("/metrics").text
            assert state.status_code == 200
            assert state.json()["travel_plan"]["requirements"]["destination"] == "Tokyo"
            assert conversation.status_code == 200
            assert conversation.json()["status"] == "planned"
            assert 'travel_planner_llm_requests_total{role="intake",status="success"}' in metrics
            assert 'travel_planner_llm_requests_total{role="planner",status="success"}' in metrics
            assert 'travel_planner_llm_requests_total{role="reviewer",status="success"}' in metrics
            assert "AsyncOpenAI" not in state.text
            assert "authorization" not in response.text.casefold()
    finally:
        asyncio.run(_cleanup(settings, thread_id, user_id))
