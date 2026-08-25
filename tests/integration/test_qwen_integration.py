"""Explicit, low-volume real Qwen invariant test."""

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import Currency, TravelPlan, TripRequirements
from app.main import create_app
from app.services.planning_service import MOCK_PLANNING_PROVIDERS

pytestmark = [
    pytest.mark.llm_integration,
    pytest.mark.skipif(
        os.getenv("RUN_LLM_INTEGRATION_TESTS") != "1",
        reason="set RUN_LLM_INTEGRATION_TESTS=1 for the paid Qwen test",
    ),
]


def test_real_qwen_planner_reviewer_and_checkpoint_invariants() -> None:
    """Run one real persistent graph and assert facts, not free-text wording."""

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
    requirements = TripRequirements(
        origin="Shanghai",
        destination="Tokyo",
        start_date=date(2027, 4, 10),
        end_date=date(2027, 4, 12),
        budget=Decimal("12000.00"),
        currency=Currency.CNY,
        travelers=1,
        preferences=["museums", "quiet walks"],
    )
    thread_id = f"p14-qwen-{uuid.uuid4().hex}"
    user_id = f"p14-user-{uuid.uuid4().hex}"
    application = create_app(settings=settings)

    with TestClient(application) as client:
        response = client.post(
            f"/api/v1/agents/threads/{thread_id}/plans",
            json={
                "user_id": user_id,
                "requirements": requirements.model_dump(mode="json"),
                "remember_preferences": ["quiet hotels"],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        plan = TravelPlan.model_validate(payload["travel_plan"])
        flights = MOCK_PLANNING_PROVIDERS.search_flights(requirements)
        hotels = MOCK_PLANNING_PROVIDERS.search_hotels(requirements)
        attractions = MOCK_PLANNING_PROVIDERS.search_attractions(requirements)
        assert plan.flight in flights
        assert plan.hotel in hotels
        known_attraction_names = {item.name for item in attractions}
        selected_visits = [
            activity.removeprefix("Visit ").split(" (", maxsplit=1)[0]
            for day in plan.daily_itinerary
            for activity in day.activities
            if activity.startswith("Visit ")
        ]
        assert set(selected_visits) <= known_attraction_names
        assert len(payload["search_summary"]) == 5
        assert 1 <= payload["review_rounds"] <= settings.review_max_rounds
        assert 0 <= payload["final_score"] <= 100

        state = client.get(f"/api/v1/agents/threads/{thread_id}/state")
        assert state.status_code == 200
        assert state.json()["travel_plan"]["requirements"]["destination"] == "Tokyo"
        metrics = client.get("/metrics").text
        assert 'travel_planner_llm_requests_total{role="planner",status="success"}' in metrics
        assert 'travel_planner_llm_requests_total{role="reviewer",status="success"}' in metrics
        assert "AsyncOpenAI" not in state.text
        assert "authorization" not in state.text.casefold()
