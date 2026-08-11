"""HTTP contract tests for the deterministic mock planning endpoint."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import TravelPlan
from app.main import create_app
from app.services import planning_service
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run the application with local resource doubles instead of Docker."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(unused_settings: Settings):
        del unused_settings
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(application) as test_client:
        yield test_client


def valid_payload() -> dict[str, object]:
    """Return the request body used by endpoint tests."""

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


def test_mock_plan_endpoint_returns_valid_travel_plan(client: TestClient) -> None:
    """A valid request returns HTTP 200 and the declared response model."""

    response = client.post("/api/v1/plans/mock", json=valid_payload())

    assert response.status_code == 200
    plan = TravelPlan.model_validate(response.json())
    assert plan.requirements.destination == "Tokyo"
    assert len(plan.daily_itinerary) == 5
    assert plan.markdown


def test_mock_plan_endpoint_is_deterministic(client: TestClient) -> None:
    """The same JSON body produces the same complete JSON response."""

    first = client.post("/api/v1/plans/mock", json=valid_payload())
    second = client.post("/api/v1/plans/mock", json=valid_payload())

    assert first.json() == second.json()


def test_mock_plan_endpoint_accepts_empty_preferences(client: TestClient) -> None:
    """Preferences are optional planning context, so an empty list remains valid."""

    payload = valid_payload()
    payload["preferences"] = []

    response = client.post("/api/v1/plans/mock", json=payload)

    assert response.status_code == 200
    assert response.json()["requirements"]["preferences"] == []


def test_mock_plan_endpoint_rejects_invalid_date_order(client: TestClient) -> None:
    """FastAPI turns Pydantic date validation into HTTP 422 automatically."""

    payload = valid_payload()
    payload["end_date"] = "2026-08-31"

    response = client.post("/api/v1/plans/mock", json=payload)

    assert response.status_code == 422


def test_mock_plan_endpoint_rejects_a_missing_field(client: TestClient) -> None:
    """A request without its destination is incomplete and receives HTTP 422."""

    payload = valid_payload()
    del payload["destination"]

    response = client.post("/api/v1/plans/mock", json=payload)

    assert response.status_code == 422


def test_service_failure_does_not_leak_a_traceback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP error contains a safe stage but not the chained private exception."""

    def fail_safely(*args: object, **kwargs: object) -> TravelPlan:
        del args, kwargs
        try:
            raise RuntimeError("private traceback token")
        except RuntimeError as exc:
            raise planning_service.PlanningServiceError("flight search") from exc

    monkeypatch.setattr(planning_service, "create_mock_travel_plan", fail_safely)

    response = client.post("/api/v1/plans/mock", json=valid_payload())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Mock travel planning could not be completed during flight search."
    }
    assert "private traceback token" not in response.text
    assert "Traceback" not in response.text
