"""Pure, stable reducers for parallel LangGraph search updates."""

import json
from collections.abc import Iterable
from typing import TypeVar

from app.search.models import (
    SEARCH_KIND_ORDER,
    SearchErrorEnvelope,
    SearchKindValue,
    SearchResultEnvelope,
    SearchSummary,
    SearchTask,
)

Envelope = TypeVar("Envelope", SearchTask, SearchResultEnvelope, SearchErrorEnvelope)
_KIND_INDEX = {kind.value: index for index, kind in enumerate(SEARCH_KIND_ORDER)}


def _canonical_json(value: object) -> str:
    """Return a stable comparison representation for JSON-safe values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _kind_sort_key(kind: SearchKindValue) -> int:
    """Map a search kind to the fixed P08 display and merge order."""

    return _KIND_INDEX[kind]


def _deduplicate(items: Iterable[Envelope]) -> list[Envelope]:
    """Choose one stable value per task ID without mutating either input."""

    by_task_id: dict[str, Envelope] = {}
    for item in items:
        task_id = item["task_id"]
        existing = by_task_id.get(task_id)
        if existing is None or _canonical_json(item) < _canonical_json(existing):
            by_task_id[task_id] = item
    return sorted(
        by_task_id.values(),
        key=lambda item: (
            _kind_sort_key(item["kind"]),
            item["task_id"],
            _canonical_json(item),
        ),
    )


def merge_search_tasks(left: list[SearchTask], right: list[SearchTask]) -> list[SearchTask]:
    """Merge tasks by stable ID so retries and replay never duplicate work records."""

    return _deduplicate([*left, *right])


def merge_search_results(
    left: list[SearchResultEnvelope],
    right: list[SearchResultEnvelope],
) -> list[SearchResultEnvelope]:
    """Merge successful parallel writes independently of completion order."""

    return _deduplicate([*left, *right])


def merge_tool_errors(
    left: list[SearchErrorEnvelope],
    right: list[SearchErrorEnvelope],
) -> list[SearchErrorEnvelope]:
    """Merge safe error records independently of completion order."""

    return _deduplicate([*left, *right])


def replace_search_summary(
    left: SearchSummary,
    right: SearchSummary,
) -> SearchSummary:
    """Replace the single aggregator's summary without mutating either mapping."""

    del left
    return dict(right)
