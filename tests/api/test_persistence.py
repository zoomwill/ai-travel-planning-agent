"""HTTP tests for durable threads and explicit user memory."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import persistence as persistence_routes
from app.core.config import Settings
from app.core.resources import AppResources
from app.main import create_app
from app.search.models import SearchKind
from tests.helpers import make_in_memory_persistence_factory, make_resource_fakes
from tests.review.helpers import FailingPlanReviewer
from tests.search.helpers import RecordingSearchBackend


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run every P07 API test with isolated in-memory persistence."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(
            lambda query: [
                "Photography, vintage shopping, quiet neighborhoods, and local food knowledge."
            ]
        ),
    )
    with TestClient(application) as test_client:
        yield test_client


def payload(
    *,
    user_id: str = "user-a",
    destination: str = "Tokyo",
    remember_preferences: list[str] | None = None,
) -> dict[str, object]:
    """Return a valid nested persistent-plan request."""

    return {
        "user_id": user_id,
        "requirements": {
            "origin": "Shanghai",
            "destination": destination,
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
            "budget": "10000.00",
            "currency": "CNY",
            "travelers": 1,
            "preferences": ["photography"],
        },
        "remember_preferences": remember_preferences or [],
    }


def test_thread_plan_state_and_history_are_available(client: TestClient) -> None:
    """A completed plan can be read back through safe state and history views."""

    plan = client.post(
        "/api/v1/agents/threads/thread-one/plans",
        json=payload(remember_preferences=["Quiet neighborhoods"]),
    )
    state = client.get("/api/v1/agents/threads/thread-one/state")
    history = client.get("/api/v1/agents/threads/thread-one/history?limit=3")

    assert plan.status_code == 200
    assert plan.json()["thread_id"] == "thread-one"
    assert plan.json()["remembered_preferences"] == ["Quiet neighborhoods"]
    assert plan.json()["search_summary"] == {
        "flights": {"status": "ok", "count": 2},
        "hotels": {"status": "ok", "count": 2},
        "attractions": {"status": "ok", "count": 3},
        "weather": {"status": "ok", "count": 3},
        "route": {"status": "ok", "count": 1},
    }
    assert plan.json()["tool_errors"] == []
    assert plan.json()["review_status"] == "accepted"
    assert plan.json()["review_rounds"] == 1
    assert plan.json()["final_score"] == 100
    assert plan.json()["finalization_reason"] == "threshold_reached"
    assert plan.json()["review_summary"]["decision"] == "accept"
    assert "## Remembered preferences" in plan.json()["travel_plan"]["markdown"]
    assert state.status_code == 200
    assert state.json()["status"] == "complete"
    assert state.json()["search_result_count"] == 5
    assert state.json()["tool_error_count"] == 0
    assert state.json()["review_status"] == "accepted"
    assert state.json()["review_round"] == 1
    assert state.json()["final_score"] == 100
    assert state.json()["finalization_reason"] == "threshold_reached"
    assert state.json()["draft_present"] is True
    assert state.json()["review_history_count"] == 1
    assert state.json()["search_summary"] == plan.json()["search_summary"]
    assert "configurable" not in state.text
    assert "search_task" not in state.text
    assert "draft_fingerprint" not in state.text
    assert history.status_code == 200
    assert len(history.json()["checkpoints"]) == 3
    assert all(item["checkpoint_id"] for item in history.json()["checkpoints"])


def test_same_user_cross_thread_recall_and_other_user_isolation(
    client: TestClient,
) -> None:
    """The HTTP boundary preserves store namespace isolation."""

    client.post(
        "/api/v1/agents/threads/thread-a/plans",
        json=payload(remember_preferences=["Local food"]),
    )
    same_user = client.post(
        "/api/v1/agents/threads/thread-b/plans",
        json=payload(),
    )
    other_user = client.post(
        "/api/v1/agents/threads/thread-c/plans",
        json=payload(user_id="user-b"),
    )

    assert same_user.json()["remembered_preferences"] == ["Local food"]
    assert other_user.json()["remembered_preferences"] == []


def test_same_thread_second_http_request_contains_only_new_destination(
    client: TestClient,
) -> None:
    """Persistent API input starts a new graph run and Prepare clears old search state."""

    first = client.post(
        "/api/v1/agents/threads/reused-thread/plans",
        json=payload(destination="Tokyo"),
    )
    second = client.post(
        "/api/v1/agents/threads/reused-thread/plans",
        json=payload(destination="Paris"),
    )
    state = client.get("/api/v1/agents/threads/reused-thread/state")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["travel_plan"]["requirements"]["destination"] == "Paris"
    assert second.json()["review_rounds"] == 1
    assert (
        second.json()["review_summary"]["draft_fingerprint"]
        != first.json()["review_summary"]["draft_fingerprint"]
    )
    assert state.json()["travel_plan"]["requirements"]["destination"] == "Paris"
    assert state.json()["search_result_count"] == 5
    assert state.json()["review_round"] == 1
    assert state.json()["review_history_count"] == 1


def test_only_explicit_preferences_are_listed(client: TestClient) -> None:
    """requirements.preferences remains current-trip context, not durable memory."""

    client.post(
        "/api/v1/agents/threads/thread-a/plans",
        json=payload(remember_preferences=["Quiet neighborhoods"]),
    )
    response = client.get("/api/v1/users/user-a/preferences")

    assert response.status_code == 200
    assert [item["value"] for item in response.json()] == ["Quiet neighborhoods"]
    assert "photography" not in response.text


def test_delete_removes_one_preference_and_missing_is_clear(client: TestClient) -> None:
    """The DELETE API targets one deterministic item and returns a stable 404."""

    client.post(
        "/api/v1/agents/threads/thread-a/plans",
        json=payload(remember_preferences=["Museums", "Local food"]),
    )
    preferences = client.get("/api/v1/users/user-a/preferences").json()
    preference_id = preferences[0]["preference_id"]

    deleted = client.delete(f"/api/v1/users/user-a/preferences/{preference_id}")
    missing = client.delete(f"/api/v1/users/user-a/preferences/{preference_id}")

    assert deleted.status_code == 204
    assert len(client.get("/api/v1/users/user-a/preferences").json()) == 1
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "preference_not_found"


@pytest.mark.parametrize(
    ("path", "body", "code"),
    [
        (
            "/api/v1/agents/threads/bad%20thread/plans",
            payload(),
            "invalid_thread_id",
        ),
        (
            "/api/v1/agents/threads/good-thread/plans",
            payload(user_id="bad user"),
            "invalid_user_id",
        ),
    ],
)
def test_invalid_identifiers_return_structured_errors(
    client: TestClient,
    path: str,
    body: dict[str, object],
    code: str,
) -> None:
    """Unsafe path and user identifiers are rejected before graph execution."""

    response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_missing_thread_and_excessive_history_limit_are_rejected(
    client: TestClient,
) -> None:
    """Missing checkpoints are clear and history cannot exceed 100 items."""

    missing = client.get("/api/v1/agents/threads/unknown-thread/state")
    excessive = client.get("/api/v1/agents/threads/unknown-thread/history?limit=101")

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "checkpoint_unavailable"
    assert excessive.status_code == 422


def test_persistence_not_initialized_is_structured() -> None:
    """A request made without lifespan startup never leaks an AttributeError."""

    application = create_app(settings=Settings(_env_file=None))
    client = TestClient(application)
    response = client.get("/api/v1/users/user-a/preferences")
    client.close()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "persistence_not_initialized"


def test_store_exception_is_sanitized(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw store exception text must never cross the HTTP boundary."""

    private_detail = "private database detail"
    monkeypatch.setattr(
        persistence_routes,
        "list_user_preferences",
        AsyncMock(side_effect=RuntimeError(private_detail)),
    )

    response = client.get("/api/v1/users/user-a/preferences")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "store_unavailable"
    assert private_detail not in response.text


def test_critical_search_exception_returns_sanitized_503() -> None:
    """Provider exception text stays out of the structured persistent API error."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(
            lambda query: [],
            search_backend=RecordingSearchBackend(fail_kind=SearchKind.FLIGHTS),
        ),
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/critical-thread/plans",
            json=payload(),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "critical_search_failed"
    assert "private backend detail" not in response.text
    assert "traceback" not in response.text.casefold()


def test_persistent_recursion_limit_returns_safe_structured_error() -> None:
    """The official GraphRecursionError never exposes runnable config or internals."""

    settings = Settings(_env_file=None, graph_recursion_limit=1)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(),
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/recursion-thread/plans",
            json=payload(),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "graph_recursion_limit_reached"
    assert "configurable" not in response.text
    assert "traceback" not in response.text.casefold()


def test_reviewer_exception_returns_safe_structured_error() -> None:
    """Reviewer exception text stays in the test process and out of HTTP."""

    settings = Settings(_env_file=None)
    fakes = make_resource_fakes(settings)

    async def resource_factory(_: Settings) -> AppResources:
        return fakes.resources

    application = create_app(
        settings=settings,
        resource_factory=resource_factory,
        persistence_factory=make_in_memory_persistence_factory(plan_reviewer=FailingPlanReviewer()),
    )
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/agents/threads/reviewer-failure-thread/plans",
            json=payload(),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "reviewer_failed"
    assert "private reviewer traceback secret" not in response.text
    assert "traceback" not in response.text.casefold()
