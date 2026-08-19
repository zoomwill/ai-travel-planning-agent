"""Opt-in live P13 API, persistence, SSE, metrics, Prometheus, and Grafana E2E."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.memory.preferences import make_preference_id, normalize_preference
from scripts.check_observability import exit_code, run_checks
from tests.api.test_streaming import parse_sse

pytestmark = [pytest.mark.integration, pytest.mark.observability]
_ENABLED = os.getenv("RUN_OBSERVABILITY_TESTS") == "1"


def _payload(user_id: str, *, remember: list[str] | None = None) -> dict[str, object]:
    return {
        "user_id": user_id,
        "requirements": {
            "origin": "P13-Origin-Fixture",
            "destination": "Tokyo",
            "start_date": "2027-04-10",
            "end_date": "2027-04-12",
            "budget": "12000.00",
            "currency": "CNY",
            "travelers": 1,
            "preferences": ["P13-current-photography"],
        },
        "remember_preferences": remember or [],
    }


async def _delete_test_data(
    settings: Settings,
    thread_ids: list[str],
    user_id: str,
    preference_ids: list[str],
) -> None:
    uri = settings.langgraph_postgres_uri.get_secret_value()
    async with AsyncPostgresSaver.from_conn_string(
        uri,
        serde=create_strict_serializer(),
    ) as saver:
        for thread_id in thread_ids:
            await saver.adelete_thread(thread_id)
    async with AsyncPostgresStore.from_conn_string(uri) as store:
        for preference_id in preference_ids:
            await store.adelete((user_id, "travel_preferences"), preference_id)


@pytest.mark.skipif(not _ENABLED, reason="set RUN_OBSERVABILITY_TESTS=1")
def test_live_observability_end_to_end() -> None:
    """Exercise real local boundaries and remove only this UUID-scoped test data."""

    unique = uuid4().hex
    user_id = f"p13-{unique}-user"
    first_thread = f"p13-{unique}-first"
    second_thread = f"p13-{unique}-memory"
    stream_thread = f"p13-{unique}-stream"
    thread_ids = [first_thread, second_thread, stream_thread]
    preference_text = f"P13 preference {unique} quiet neighborhoods"
    settings = Settings()
    preference_ids = [make_preference_id(user_id, normalize_preference(preference_text))]

    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as client:
            first = client.post(
                f"/api/v1/agents/threads/{first_thread}/plans",
                json=_payload(user_id, remember=[preference_text]),
                headers={"X-Request-ID": f"p13-{unique}-first-request"},
            )
            assert first.status_code == 200
            assert first.headers["x-request-id"] == f"p13-{unique}-first-request"
            assert first.json()["search_backend_mode"] == "direct"
            assert len(first.json()["search_summary"]) == 5
            assert first.json()["review_status"] in {"accepted", "forced_finalized"}
            assert first.json()["retrieval_query_variants"]
            saved = client.get(f"/api/v1/users/{user_id}/preferences")
            assert saved.status_code == 200 and len(saved.json()) == 1
            assert [item["preference_id"] for item in saved.json()] == preference_ids

            second = client.post(
                f"/api/v1/agents/threads/{second_thread}/plans",
                json=_payload(user_id),
            )
            assert second.status_code == 200
            assert any(unique in value for value in second.json()["remembered_preferences"])

            streamed = client.post(
                f"/api/v1/agents/threads/{stream_thread}/plans/stream",
                json=_payload(user_id),
            )
            assert streamed.status_code == 200
            events, comments = parse_sse(streamed.text)
            event_types = [event["event_type"] for event in events]
            assert event_types[0] == "run_started"
            assert event_types[-1] == "plan_completed"
            assert event_types.count("plan_completed") == 1
            assert "error" not in event_types
            assert {
                event["data"].get("search_kind")
                for event in events
                if event["event_type"] == "search_started"
            } == {"flights", "hotels", "attractions", "weather", "route"}
            assert all(comment == "ping" for comment in comments)

            state = client.get(f"/api/v1/agents/threads/{first_thread}/state")
            history = client.get(f"/api/v1/agents/threads/{first_thread}/history")
            assert state.status_code == 200 and state.json()["status"] == "complete"
            assert history.status_code == 200 and history.json()["checkpoints"]

            request_ids = [f"p13-{unique}-concurrent-{index}" for index in range(4)]

            def correlated(request_id: str) -> str:
                response = client.get("/health", headers={"X-Request-ID": request_id})
                assert response.status_code == 200
                return response.headers["x-request-id"]

            with ThreadPoolExecutor(max_workers=4) as executor:
                returned_ids = list(executor.map(correlated, request_ids))
            assert returned_ids == request_ids

            metrics = client.get("/metrics")
            assert metrics.status_code == 200
            assert "travel_planner_graph_runs_total" in metrics.text
            assert "travel_planner_search_tasks_total" in metrics.text
            assert "travel_planner_sse_connections_active 0.0" in metrics.text
            assert 'event_type="plan_completed"' in metrics.text
            for private_value in (
                user_id,
                first_thread,
                second_thread,
                stream_thread,
                preference_text,
                "P13-Origin-Fixture",
            ):
                assert private_value not in metrics.text

            preferences = client.get(f"/api/v1/users/{user_id}/preferences")
            assert preferences.status_code == 200
            for preference in preferences.json():
                deleted = client.delete(
                    f"/api/v1/users/{user_id}/preferences/{preference['preference_id']}"
                )
                assert deleted.status_code == 204

        results = run_checks(
            "http://127.0.0.1:8000",
            "http://127.0.0.1:9090",
            "http://127.0.0.1:3000",
        )
        assert exit_code(results) == 0, results
    finally:
        asyncio.run(_delete_test_data(settings, thread_ids, user_id, preference_ids))
