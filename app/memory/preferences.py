"""Deterministic operations for explicit user preference memory."""

import hashlib
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime

from langgraph.store.base import BaseStore

from app.memory.models import PreferenceCategory, PreferenceMemory

PREFERENCE_NAMESPACE = "travel_preferences"

_CATEGORY_KEYWORDS: tuple[tuple[PreferenceCategory, tuple[str, ...]], ...] = (
    (
        PreferenceCategory.PACE,
        ("slow", "relaxed", "leisurely", "fast-paced", "pace", "慢", "轻松", "节奏"),
    ),
    (
        PreferenceCategory.CROWD_PREFERENCE,
        ("quiet", "uncrowded", "crowd", "busy", "安静", "人少", "拥挤"),
    ),
    (
        PreferenceCategory.FOOD,
        ("food", "cuisine", "restaurant", "vegetarian", "vegan", "美食", "餐厅", "素食"),
    ),
    (
        PreferenceCategory.ACCOMMODATION,
        ("hotel", "hostel", "accommodation", "room", "酒店", "旅馆", "住宿"),
    ),
    (
        PreferenceCategory.TRANSPORT,
        ("train", "metro", "bus", "walk", "transport", "火车", "地铁", "公交", "步行"),
    ),
    (
        PreferenceCategory.INTEREST,
        (
            "museum",
            "art",
            "photography",
            "history",
            "culture",
            "hiking",
            "shopping",
            "博物馆",
            "艺术",
            "摄影",
            "历史",
            "文化",
            "徒步",
            "购物",
        ),
    ),
)


def preference_namespace(user_id: str) -> tuple[str, str]:
    """Return the exact namespace reserved for one user's travel preferences."""

    return (user_id, PREFERENCE_NAMESPACE)


def clean_preference_value(value: str) -> str:
    """Normalize Unicode and whitespace while preserving readable letter case."""

    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_preference(value: str) -> str:
    """Return the stable comparison form used for deduplication and identifiers."""

    return clean_preference_value(value).casefold()


def make_preference_id(user_id: str, normalized_value: str) -> str:
    """Build a deterministic identifier without exposing the raw user or preference."""

    source = f"{user_id}\x1f{normalized_value}".encode()
    return hashlib.sha256(source).hexdigest()[:24]


def categorize_preference(normalized_value: str) -> PreferenceCategory:
    """Choose a category through transparent keyword matching."""

    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in normalized_value for keyword in keywords):
            return category
    return PreferenceCategory.GENERAL


async def upsert_explicit_preferences(
    store: BaseStore,
    *,
    user_id: str,
    source_thread_id: str,
    values: Iterable[str],
    now: datetime | None = None,
) -> list[PreferenceMemory]:
    """Insert or update only the preference strings explicitly supplied by a user."""

    timestamp = now or datetime.now(UTC)
    namespace = preference_namespace(user_id)
    unique_values: dict[str, str] = {}
    for value in values:
        cleaned = clean_preference_value(value)
        normalized = normalize_preference(cleaned)
        if normalized:
            unique_values.setdefault(normalized, cleaned)

    saved: list[PreferenceMemory] = []
    for normalized, cleaned in unique_values.items():
        preference_id = make_preference_id(user_id, normalized)
        existing_item = await store.aget(namespace, preference_id)
        created_at = timestamp
        if existing_item is not None:
            existing = PreferenceMemory.model_validate(existing_item.value)
            created_at = existing.created_at

        memory = PreferenceMemory(
            preference_id=preference_id,
            value=cleaned,
            normalized_value=normalized,
            category=categorize_preference(normalized),
            source_thread_id=source_thread_id,
            created_at=created_at,
            updated_at=timestamp,
        )
        await store.aput(
            namespace,
            preference_id,
            memory.model_dump(mode="json"),
            index=False,
        )
        saved.append(memory)
    return saved


async def list_user_preferences(store: BaseStore, user_id: str) -> list[PreferenceMemory]:
    """List one user's saved preferences in deterministic order."""

    items = await store.asearch(preference_namespace(user_id), limit=1000)
    memories = [PreferenceMemory.model_validate(item.value) for item in items]
    return sorted(memories, key=lambda item: (item.normalized_value, item.preference_id))


async def delete_user_preference(
    store: BaseStore,
    *,
    user_id: str,
    preference_id: str,
) -> bool:
    """Delete exactly one preference and report whether it existed."""

    namespace = preference_namespace(user_id)
    if await store.aget(namespace, preference_id) is None:
        return False
    await store.adelete(namespace, preference_id)
    return True
