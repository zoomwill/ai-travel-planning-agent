"""Non-empty, same-public-UUID isolation with test JWTs; optional local PostgreSQL."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.auth.tokens import user_reference
from app.core.config import Settings
from app.core.persistence import PersistenceResources, create_strict_serializer
from app.graphs.graph import build_travel_planning_graph
from tests.api.test_persistence import payload
from tests.helpers import make_in_memory_persistence_factory


@pytest.fixture
def identities(auth_settings):
    public = str(uuid4())
    subjects = ["auth0|p19-" + str(uuid4()) for _ in range(2)]
    refs = [user_reference(auth_settings.auth0_issuer, subject) for subject in subjects]
    return public, subjects, refs


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def auth_persistence_factory(request, identities):
    """Use only test-owned namespaces; never wipe a table, schema, or database."""
    if request.param == "memory":
        return make_in_memory_persistence_factory()
    if os.getenv("RUN_P19_POSTGRES_TESTS") != "1" and os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_P19_POSTGRES_TESTS=1 for explicit local PostgreSQL isolation")
    uri = Settings().langgraph_postgres_uri.get_secret_value()
    if urlsplit(uri).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("P19 integration helper refuses non-local PostgreSQL")
    public, _, refs = identities

    @asynccontextmanager
    async def factory(settings, *args, **kwargs):
        async with AsyncPostgresSaver.from_conn_string(
            uri, serde=create_strict_serializer()
        ) as saver:
            async with AsyncPostgresStore.from_conn_string(uri) as store:
                await saver.setup()
                await store.setup()
                graph = build_travel_planning_graph(lambda _: [], checkpointer=saver, store=store)
                try:
                    yield PersistenceResources(checkpointer=saver, store=store, graph=graph)
                finally:
                    for ref in refs:
                        await saver.adelete_thread(f"auth0:{ref}:{public}")
                        await store.adelete((ref, "trip_intake"), public)
                        for item in await store.asearch((ref, "travel_preferences"), limit=100):
                            await store.adelete(item.namespace, item.key)

    return factory


def test_two_nonempty_users_same_uuid_and_spoofing(auth_client, token, identities):
    client, _, _ = auth_client
    public, subjects, refs = identities
    root = f"/api/v1/agents/threads/{public}"
    headers = [{"Authorization": "Bearer " + token(subject)} for subject in subjects]
    for index, city in enumerate(("Tokyo", "Paris")):
        response = client.post(
            root + "/conversation/messages",
            json={"message": f"Private P19 {city} draft", "user_id": refs[1 - index]},
            headers=headers[index],
        )
        assert response.status_code == 200
        assert response.json()["draft"]["destination"] == city
        response = client.post(
            root + "/plans",
            headers=headers[index],
            json=payload(
                user_id=refs[1 - index],
                destination=city,
                remember_preferences=[f"P19 {city} photography"],
            ),
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == refs[index]

    for index, city in enumerate(("Tokyo", "Paris")):
        other = ("Paris", "Tokyo")[index]
        conversation = client.get(
            root + f"/conversation?user_id={refs[1 - index]}", headers=headers[index]
        )
        assert conversation.json()["draft"]["destination"] == city
        assert f"Private P19 {other}" not in conversation.text
        state = client.get(root + f"/state?user_id={refs[1 - index]}", headers=headers[index])
        assert state.json()["travel_plan"]["requirements"]["destination"] == city
        assert state.json()["travel_plan"]["quality"]["review_status"] in {
            "accepted",
            "forced_finalized",
        }
        history = client.get(root + "/history", headers=headers[index]).json()["checkpoints"]
        assert history and history[0]["quality"] == state.json()["travel_plan"]["quality"]
        own = client.get("/api/v1/me/preferences", headers=headers[index]).json()
        assert len(own) == 1 and city in own[0]["value"]
        spoof = client.get(f"/api/v1/users/{refs[1 - index]}/preferences", headers=headers[index])
        assert spoof.json() == own
        cross_delete = client.delete(
            f"/api/v1/users/{refs[index]}/preferences/{own[0]['preference_id']}",
            headers=headers[1 - index],
        )
        assert cross_delete.status_code == 404
        assert client.get("/api/v1/me/preferences", headers=headers[index]).json() == own
    a_history = client.get(root + "/history", headers=headers[0]).json()["checkpoints"]
    b_history = client.get(root + "/history", headers=headers[1]).json()["checkpoints"]
    assert {x["checkpoint_id"] for x in a_history}.isdisjoint(x["checkpoint_id"] for x in b_history)
    assert client.get(root + "/state").status_code == 401
    assert client.post(root + "/plans/stream", json=payload()).status_code == 401
    # A changes its non-empty draft after both plans/preferences already exist.
    changed = client.post(
        root + "/conversation/messages",
        json={"message": "Change my private destination to London", "user_id": refs[1]},
        headers=headers[0],
    )
    assert changed.status_code == 200
    assert changed.json()["draft"]["destination"] == "London"
    b_conversation = client.get(root + "/conversation", headers=headers[1])
    assert b_conversation.json()["draft"]["destination"] == "Paris"
    assert "London" not in b_conversation.text
    assert (
        client.get(root + "/state", headers=headers[1]).json()["travel_plan"]["requirements"][
            "destination"
        ]
        == "Paris"
    )
