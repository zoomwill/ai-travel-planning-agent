"""Every protected API uses the cryptographically verified principal."""

from unittest.mock import AsyncMock

import pytest

from tests.api.test_persistence import payload

ROOT = "/api/v1/agents/threads/same-public-thread"


def bearer(value):
    return {"Authorization": "Bearer " + value}


@pytest.mark.parametrize("header", [None, "Basic fake", "Bearer", "Bearer a b", "Bearer not-a-jwt"])
def test_missing_or_malformed_bearer(auth_client, header):
    client, _, _ = auth_client
    response = client.get(
        ROOT + "/state", headers={} if header is None else {"Authorization": header}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"]["code"] == "authentication_required"


@pytest.mark.parametrize(
    "path",
    [
        ROOT + "/state",
        ROOT + "/history",
        ROOT + "/conversation",
        "/api/v1/me/preferences",
        "/api/v1/users/spoof/preferences",
        "/api/v1/rag/status",
        "/api/v1/mcp/status",
        "/api/v1/llm/status",
        "/api/v1/travel-data/status",
    ],
)
def test_get_routes_protected(auth_client, path):
    client, _, _ = auth_client
    assert client.get(path).status_code == 401
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        ROOT + "/plans",
        ROOT + "/plans/stream",
        ROOT + "/conversation/messages",
        ROOT + "/conversation/reset",
        ROOT + "/conversation/confirm",
        ROOT + "/conversation/confirm/stream",
        "/api/v1/agents/plans",
        "/api/v1/plans/mock",
        "/api/v1/rag/search",
    ],
)
def test_mutations_protected_before_body_or_stream(auth_client, path):
    client, fakes, _ = auth_client
    response = client.post(path, json={})
    assert response.status_code == 401
    assert "text/event-stream" not in response.headers.get("content-type", "")
    fakes.resources.redis_client.eval.assert_not_awaited()


def test_two_users_same_thread_plans_history_preferences(auth_client, token):
    client, _, _ = auth_client
    a, b = bearer(token()), bearer(token("auth0|user-b"))
    first = client.post(
        ROOT + "/plans", json=payload(user_id="user-b", remember_preferences=["Quiet"]), headers=a
    )
    assert first.status_code == 200
    assert first.json()["thread_id"] == "same-public-thread"
    assert first.json()["user_id"] != "user-b"
    assert "auth0|" not in first.text
    assert client.get(ROOT + "/state", headers=b).status_code == 404
    assert client.get(ROOT + "/history", headers=b).json()["checkpoints"] == []
    pref = client.get("/api/v1/me/preferences", headers=a).json()[0]
    assert pref["source_thread_id"] == "same-public-thread"
    assert client.get("/api/v1/users/user-a/preferences", headers=b).json() == []
    response = client.delete("/api/v1/me/preferences/" + pref["preference_id"], headers=b)
    assert response.status_code == 404
    second = client.post(ROOT + "/plans", json=payload(destination="Paris"), headers=b)
    assert second.status_code == 200
    assert (
        client.get(ROOT + "/state", headers=a).json()["travel_plan"]["requirements"]["destination"]
        == "Tokyo"
    )
    assert (
        client.get(ROOT + "/state", headers=b).json()["travel_plan"]["requirements"]["destination"]
        == "Paris"
    )
    assert (
        client.get(ROOT + "/history", headers=a).json()
        != client.get(ROOT + "/history", headers=b).json()
    )
    assert len(client.get("/api/v1/me/preferences", headers=a).json()) == 1


def test_conversation_confirm_stream_and_reset_isolation(auth_client, token):
    client, _, _ = auth_client
    a, b = bearer(token()), bearer(token("auth0|user-b"))
    ready = client.post(
        ROOT + "/conversation/messages", json={"message": "A trip", "user_id": "spoof"}, headers=a
    )
    assert ready.status_code == 200
    assert client.get(ROOT + "/conversation?user_id=spoof", headers=b).status_code == 404
    other = client.post(ROOT + "/conversation/messages", json={"message": "B trip"}, headers=b)
    assert other.status_code == 200
    assert other.json()["draft"]["destination"] == "Paris"
    stream = client.post(
        ROOT + "/conversation/confirm/stream",
        json={"draft_fingerprint": ready.json()["draft_fingerprint"]},
        headers=a,
    )
    assert stream.status_code == 200
    assert stream.text.count("event: plan_completed") == 1
    assert "auth0:" not in stream.text
    assert client.get(ROOT + "/conversation", headers=a).json()["plan_available"] is True
    assert client.get(ROOT + "/conversation", headers=b).json()["plan_available"] is False
    reset = client.post(ROOT + "/conversation/reset", json={}, headers=b)
    assert reset.status_code == 200
    assert client.get(ROOT + "/conversation", headers=a).json()["draft"]["destination"] == "Tokyo"


@pytest.mark.parametrize("result,status", [(42, 429), (ConnectionError("private"), 503)])
def test_rate_limit_prevents_execution_and_sse(auth_client, token, result, status):
    client, fakes, _ = auth_client
    fakes.resources.redis_client.eval = AsyncMock(
        side_effect=result if isinstance(result, Exception) else None,
        return_value=result if isinstance(result, int) else 0,
    )
    response = client.post(ROOT + "/plans/stream", json=payload(), headers=bearer(token()))
    assert response.status_code == status
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert "private" not in response.text
    if status == 429:
        assert response.headers["retry-after"] == "42"
    assert client.get(ROOT + "/state", headers=bearer(token())).status_code == 404


def test_metrics_bounded_and_no_token_or_subject(auth_client, token):
    client, fakes, _ = auth_client
    value = token()
    client.get(ROOT + "/state", headers=bearer(value))
    text = client.get("/metrics").text
    assert "travel_planner_auth_events_total" in text
    assert value not in text and "auth0|" not in text and "kid=" not in text
    assert 'operation="authorization",outcome="denied"' in text
