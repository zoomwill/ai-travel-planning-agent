"""Pure reducer for retry-safe review history accumulation."""

import json
from collections.abc import Iterable

from app.review.models import ReviewHistoryEntry
from app.search.models import JsonObject, dump_model_json


def _canonical_json(entry: JsonObject) -> str:
    """Return one stable comparison string for a JSON-safe history entry."""

    return json.dumps(
        entry,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _deduplicate(entries: Iterable[JsonObject]) -> list[JsonObject]:
    """Choose one deterministic entry per round and draft fingerprint."""

    by_identity: dict[tuple[int, str], JsonObject] = {}
    for raw_entry in entries:
        model = ReviewHistoryEntry.model_validate(raw_entry)
        entry = dump_model_json(model)
        identity = (model.review_round, model.draft_fingerprint)
        existing = by_identity.get(identity)
        if existing is None or _canonical_json(entry) < _canonical_json(existing):
            by_identity[identity] = entry
    return [by_identity[identity] for identity in sorted(by_identity)]


def merge_review_history(
    left: list[JsonObject],
    right: list[JsonObject],
) -> list[JsonObject]:
    """Merge review entries without mutation, duplication, or completion-order effects."""

    return _deduplicate([*left, *right])
