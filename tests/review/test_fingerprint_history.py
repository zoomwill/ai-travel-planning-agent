"""Tests for canonical draft identity and retry-safe review history."""

from app.review.fingerprint import create_draft_fingerprint
from app.review.history import merge_review_history
from app.review.models import ReviewDecision, ReviewHistoryEntry, ReviewIssueCode
from app.search.models import dump_model_json
from tests.review.helpers import make_review_plan


def history_entry(round_number: int, fingerprint: str) -> ReviewHistoryEntry:
    """Build one stable history entry for reducer tests."""

    return ReviewHistoryEntry(
        review_round=round_number,
        draft_fingerprint=fingerprint,
        overall_score=75,
        decision=ReviewDecision.REVISE,
        issue_codes=[ReviewIssueCode.PERSONALIZATION_MISSING],
        critique="Apply preference feedback.",
        applied_feedback=[],
    )


def test_fingerprint_is_stable_and_includes_markdown() -> None:
    """Every structured field, including human-readable Markdown, identifies a draft."""

    plan = make_review_plan()
    same = plan.model_copy(deep=True)
    changed = plan.model_copy(update={"markdown": f"{plan.markdown}\nChanged"})

    assert create_draft_fingerprint(plan) == create_draft_fingerprint(same)
    assert create_draft_fingerprint(plan) != create_draft_fingerprint(changed)


def test_history_reducer_deduplicates_retries_and_sorts_by_round() -> None:
    """Replay order cannot duplicate or reorder validated review records."""

    first_fingerprint = "a" * 64
    second_fingerprint = "b" * 64
    first = dump_model_json(history_entry(1, first_fingerprint))
    second = dump_model_json(history_entry(2, second_fingerprint))

    merged = merge_review_history([second, first], [first])

    assert len(merged) == 2
    assert [entry["review_round"] for entry in merged] == [1, 2]
    assert [entry["draft_fingerprint"] for entry in merged] == [
        first_fingerprint,
        second_fingerprint,
    ]
