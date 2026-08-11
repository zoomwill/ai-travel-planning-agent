"""HTTP tests for the Phase P05 LangGraph planning endpoint."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import TravelPlan
from app.graphs.graph import build_travel_planning_graph
from app.main import create_app
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run FastAPI with local resource doubles instead of Docker."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(unused_settings: Settings):
        del unused_settings
        return fakes.resources

    def retrieve_context(query: str) -> list[str]:
        assert "Tokyo" in query
        return ["Yanaka is suitable for street photography."]

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
        travel_graph=build_travel_planning_graph(retrieve_context),
    )
    with TestClient(application) as test_client:
        yield test_client


def valid_payload() -> dict[str, object]:
    """Return a valid structured request for the Agent endpoint."""

    return {
        "origin": "Shanghai",
        "destination": "Tokyo",
        "start_date": "2026-09-01",
        "end_date": "2026-09-05",
        "budget": "10000.00",
        "currency": "CNY",
        "travelers": 1,
        "preferences": ["photography", "vintage shopping"],
    }


def test_agent_plan_endpoint_returns_a_valid_travel_plan(client: TestClient) -> None:
    """A valid request runs the graph and returns HTTP 200."""

    response = client.post("/api/v1/agents/plans", json=valid_payload())

    assert response.status_code == 200
    plan = TravelPlan.model_validate(response.json())
    assert plan.requirements.destination == "Tokyo"
    assert len(plan.daily_itinerary) == 5
    assert plan.total_cost > 0
    assert "Yanaka is suitable for street photography." in plan.markdown


def test_agent_plan_endpoint_is_deterministic(client: TestClient) -> None:
    """Repeated HTTP requests preserve deterministic graph behavior."""

    first = client.post("/api/v1/agents/plans", json=valid_payload())
    second = client.post("/api/v1/agents/plans", json=valid_payload())

    assert first.json() == second.json()


def test_agent_plan_endpoint_uses_request_validation(client: TestClient) -> None:
    """An impossible date order is rejected before graph execution."""

    payload = valid_payload()
    payload["end_date"] = "2026-08-31"

    response = client.post("/api/v1/agents/plans", json=payload)

    assert response.status_code == 422
