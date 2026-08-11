"""Pure and in-memory tests for deterministic preference operations."""

from datetime import UTC, datetime

import pytest
from langgraph.store.memory import InMemoryStore

from app.memory.models import PreferenceCategory
from app.memory.preferences import (
    categorize_preference,
    delete_user_preference,
    list_user_preferences,
    make_preference_id,
    normalize_preference,
    upsert_explicit_preferences,
)


def test_normalization_is_unicode_whitespace_and_case_stable() -> None:
    """Equivalent human input receives one comparison value."""

    assert normalize_preference("  Quiet\u3000Neighborhoods  ") == "quiet neighborhoods"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("relaxed pace", PreferenceCategory.PACE),
        ("quiet streets", PreferenceCategory.CROWD_PREFERENCE),
        ("local food", PreferenceCategory.FOOD),
        ("small hotel", PreferenceCategory.ACCOMMODATION),
        ("travel by train", PreferenceCategory.TRANSPORT),
        ("art museums", PreferenceCategory.INTEREST),
        ("window seat", PreferenceCategory.GENERAL),
    ],
)
def test_category_rules_are_deterministic(
    value: str,
    expected: PreferenceCategory,
) -> None:
    """Transparent keyword rules always return the expected category."""

    assert categorize_preference(value) is expected


def test_preference_ids_deduplicate_per_user_but_isolate_users() -> None:
    """The same user's duplicate is stable while a second user's ID differs."""

    normalized = normalize_preference("Quiet neighborhoods")
    assert make_preference_id("user-a", normalized) == make_preference_id("user-a", normalized)
    assert make_preference_id("user-a", normalized) != make_preference_id("user-b", normalized)


@pytest.mark.asyncio
async def test_duplicate_upsert_preserves_creation_and_updates_source() -> None:
    """Saving an equivalent value updates one item instead of creating two."""

    store = InMemoryStore()
    created = datetime(2026, 8, 11, 9, tzinfo=UTC)
    updated = datetime(2026, 8, 11, 10, tzinfo=UTC)

    first = await upsert_explicit_preferences(
        store,
        user_id="user-a",
        source_thread_id="thread-one",
        values=["Quiet neighborhoods"],
        now=created,
    )
    second = await upsert_explicit_preferences(
        store,
        user_id="user-a",
        source_thread_id="thread-two",
        values=[" quiet   NEIGHBORHOODS "],
        now=updated,
    )
    memories = await list_user_preferences(store, "user-a")

    assert first[0].preference_id == second[0].preference_id
    assert len(memories) == 1
    assert memories[0].created_at == created
    assert memories[0].updated_at == updated
    assert memories[0].source_thread_id == "thread-two"


@pytest.mark.asyncio
async def test_list_is_sorted_and_namespaces_are_isolated() -> None:
    """Each user sees only their own deterministically sorted values."""

    store = InMemoryStore()
    await upsert_explicit_preferences(
        store,
        user_id="user-a",
        source_thread_id="thread-a",
        values=["Museums", "Local food"],
    )
    await upsert_explicit_preferences(
        store,
        user_id="user-b",
        source_thread_id="thread-b",
        values=["Window seat"],
    )

    assert [item.value for item in await list_user_preferences(store, "user-a")] == [
        "Local food",
        "Museums",
    ]
    assert [item.value for item in await list_user_preferences(store, "user-b")] == ["Window seat"]


@pytest.mark.asyncio
async def test_delete_removes_exactly_one_item_and_reports_missing() -> None:
    """A delete never clears the rest of a user's namespace."""

    store = InMemoryStore()
    saved = await upsert_explicit_preferences(
        store,
        user_id="user-a",
        source_thread_id="thread-a",
        values=["Museums", "Local food"],
    )

    assert await delete_user_preference(
        store,
        user_id="user-a",
        preference_id=saved[0].preference_id,
    )
    assert not await delete_user_preference(
        store,
        user_id="user-a",
        preference_id=saved[0].preference_id,
    )
    assert len(await list_user_preferences(store, "user-a")) == 1
