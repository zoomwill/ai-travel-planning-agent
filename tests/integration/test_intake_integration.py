"""Opt-in real PostgreSQL Store restart recovery for conversational intake."""

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import Settings
from app.core.resources import AppResources
from app.intake.models import TripRequirementPatch
from app.llm.diagnostics import LLMRuntimeDiagnostics
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.models import QwenTripRequirementExtraction
from app.llm.runtime import LLMRuntime
from app.main import create_app
from tests.helpers import make_resource_fakes

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 for real PostgreSQL Store recovery",
    ),
]


def _application(
    settings: Settings,
    extraction: QwenTripRequirementExtraction,
):
    """Create an app with real persistence and a no-network intake provider."""

    provider = FakeStructuredLLMProvider(intake_extractions=[extraction])
    fakes = make_resource_fakes(settings)
    fakes.resources.llm_runtime = LLMRuntime(
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

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    return create_app(settings=settings, resource_factory=resource_factory)


async def _delete_intakes(settings: Settings, user_ids: tuple[str, ...], thread_id: str) -> None:
    """Delete only UUID-scoped Store keys created by this test."""

    async with AsyncPostgresStore.from_conn_string(
        settings.langgraph_postgres_uri.get_secret_value()
    ) as store:
        for user_id in user_ids:
            await store.adelete((user_id, "trip_intake"), thread_id)


def test_intake_survives_app_restart_and_remains_user_isolated() -> None:
    """Close one FastAPI lifespan, reopen it, recover, then continue the draft."""

    settings = Settings().model_copy(update={"agent_reasoning_mode": "deterministic"})
    unique = uuid4().hex
    thread_id = f"p15-{unique}-restart"
    user_id = f"p15-{unique}-user"
    other_user = f"p15-{unique}-other"
    try:
        first_extraction = QwenTripRequirementExtraction(
            patch=TripRequirementPatch(destination="Tokyo")
        )
        with TestClient(_application(settings, first_extraction)) as first_client:
            first = first_client.post(
                f"/api/v1/agents/threads/{thread_id}/conversation/messages",
                json={"user_id": user_id, "message": "I want to visit Tokyo."},
            )
            assert first.status_code == 200
            assert first.json()["draft"]["destination"] == "Tokyo"

        second_extraction = QwenTripRequirementExtraction(
            patch=TripRequirementPatch(
                origin="Cleveland",
                start_date="2027-10-12",
                duration_days=5,
            )
        )
        with TestClient(_application(settings, second_extraction)) as restarted:
            recovered = restarted.get(
                f"/api/v1/agents/threads/{thread_id}/conversation?user_id={user_id}"
            )
            isolated = restarted.get(
                f"/api/v1/agents/threads/{thread_id}/conversation?user_id={other_user}"
            )
            continued = restarted.post(
                f"/api/v1/agents/threads/{thread_id}/conversation/messages",
                json={
                    "user_id": user_id,
                    "message": "From Cleveland on October 12 for five days.",
                },
            )

        assert recovered.status_code == 200
        assert recovered.json()["turn_count"] == 1
        assert isolated.status_code == 404
        assert continued.status_code == 200
        assert continued.json()["draft"]["destination"] == "Tokyo"
        assert continued.json()["draft"]["origin"] == "Cleveland"
        assert continued.json()["draft"]["end_date"] == "2027-10-16"
        assert continued.json()["turn_count"] == 2
    finally:
        asyncio.run(_delete_intakes(settings, (user_id, other_user), thread_id))
