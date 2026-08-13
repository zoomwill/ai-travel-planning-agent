"""Injectable deterministic reviewer for structured travel-plan quality."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from app.domain.models import QualityScore, TravelPlan, TripRequirements
from app.review.fingerprint import create_draft_fingerprint
from app.review.models import (
    PlanReview,
    ReviewDecision,
    ReviewIssueCode,
)
from app.search.models import SearchErrorEnvelope, SearchSummary

_ISSUE_ORDER: tuple[ReviewIssueCode, ...] = (
    ReviewIssueCode.MISSING_REQUIRED_CONTENT,
    ReviewIssueCode.BUDGET_OVERRUN,
    ReviewIssueCode.ITINERARY_TOO_DENSE,
    ReviewIssueCode.PERSONALIZATION_MISSING,
    ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE,
    ReviewIssueCode.INCONSISTENT_DATES,
    ReviewIssueCode.INVALID_COST_BREAKDOWN,
    ReviewIssueCode.GENERAL_QUALITY_ISSUE,
)

_CRITIQUE_BY_ISSUE: dict[ReviewIssueCode, str] = {
    ReviewIssueCode.MISSING_REQUIRED_CONTENT: (
        "The draft is missing required flight, hotel, itinerary, date, or cost content."
    ),
    ReviewIssueCode.BUDGET_OVERRUN: (
        "The estimated total exceeds the user's budget; choose lower-cost valid options."
    ),
    ReviewIssueCode.ITINERARY_TOO_DENSE: (
        "At least one day has more than two optional attraction visits."
    ),
    ReviewIssueCode.PERSONALIZATION_MISSING: (
        "One or more current or remembered preferences are not reflected in the plan."
    ),
    ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE: (
        "One or more non-critical searches are unavailable and must remain clearly disclosed."
    ),
    ReviewIssueCode.INCONSISTENT_DATES: (
        "The itinerary dates or day numbers do not match the requested inclusive date range."
    ),
    ReviewIssueCode.INVALID_COST_BREAKDOWN: (
        "The plan contains a missing, zero, negative, or inconsistent cost value."
    ),
    ReviewIssueCode.GENERAL_QUALITY_ISSUE: (
        "The equal-weight overall score is below the configured threshold."
    ),
}

_CHANGE_BY_ISSUE: dict[ReviewIssueCode, str] = {
    ReviewIssueCode.MISSING_REQUIRED_CONTENT: "Restore all required structured plan fields.",
    ReviewIssueCode.BUDGET_OVERRUN: (
        "Select the cheapest valid flight and hotel and prefer lower-cost activities."
    ),
    ReviewIssueCode.ITINERARY_TOO_DENSE: (
        "Limit optional attraction visits to one per day while keeping every trip date."
    ),
    ReviewIssueCode.PERSONALIZATION_MISSING: (
        "Deterministically prioritize attractions that match traveler preferences."
    ),
    ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE: (
        "Keep explicit unavailable-data notices instead of inventing results."
    ),
    ReviewIssueCode.INCONSISTENT_DATES: "Rebuild one itinerary entry per requested date.",
    ReviewIssueCode.INVALID_COST_BREAKDOWN: "Recalculate costs only from validated provider data.",
    ReviewIssueCode.GENERAL_QUALITY_ISSUE: "Apply every actionable structured review issue.",
}


class PlanReviewer(Protocol):
    """Async review boundary that graph tests can replace without an LLM."""

    async def review(
        self,
        *,
        draft: TravelPlan,
        requirements: TripRequirements,
        search_summary: SearchSummary,
        retrieved_context: Sequence[str],
        remembered_preferences: Sequence[str],
        tool_errors: Sequence[SearchErrorEnvelope],
        review_round: int,
        score_threshold: float,
        max_review_rounds: int,
    ) -> PlanReview:
        """Return one validated structured review for the supplied draft."""


def decide_review(
    *,
    overall_score: float,
    score_threshold: float,
    review_round: int,
    max_review_rounds: int,
) -> ReviewDecision:
    """Apply threshold and bounded-round rules without an off-by-one error."""

    if overall_score >= score_threshold:
        return ReviewDecision.ACCEPT
    if review_round >= max_review_rounds:
        return ReviewDecision.FORCED_FINALIZE
    return ReviewDecision.REVISE


class DeterministicPlanReviewer:
    """Score structured plans through documented local rules only."""

    async def review(
        self,
        *,
        draft: TravelPlan,
        requirements: TripRequirements,
        search_summary: SearchSummary,
        retrieved_context: Sequence[str],
        remembered_preferences: Sequence[str],
        tool_errors: Sequence[SearchErrorEnvelope],
        review_round: int,
        score_threshold: float,
        max_review_rounds: int,
    ) -> PlanReview:
        """Return the same scores and guidance for the same complete input."""

        issue_set: set[ReviewIssueCode] = set()
        completeness = _score_completeness(
            draft,
            requirements,
            search_summary,
            tool_errors,
            issue_set,
        )
        feasibility = _score_feasibility(draft, requirements, issue_set)
        personalization = _score_personalization(
            draft,
            requirements,
            retrieved_context,
            remembered_preferences,
            issue_set,
        )
        budget_fit = _score_budget_fit(draft, requirements, issue_set)
        overall_score = round(
            (completeness + feasibility + personalization + budget_fit) / 4,
            2,
        )
        decision = decide_review(
            overall_score=overall_score,
            score_threshold=score_threshold,
            review_round=review_round,
            max_review_rounds=max_review_rounds,
        )
        if decision is not ReviewDecision.ACCEPT and not issue_set:
            issue_set.add(ReviewIssueCode.GENERAL_QUALITY_ISSUE)

        issue_codes = [issue for issue in _ISSUE_ORDER if issue in issue_set]
        critique = _build_critique(decision, issue_codes, score_threshold)
        scores = QualityScore(
            completeness=completeness,
            feasibility=feasibility,
            personalization=personalization,
            budget_fit=budget_fit,
            overall_score=overall_score,
            critique=critique,
        )
        return PlanReview(
            review_round=review_round,
            draft_fingerprint=create_draft_fingerprint(draft),
            scores=scores,
            decision=decision,
            issue_codes=issue_codes,
            critique=critique,
            suggested_changes=[_CHANGE_BY_ISSUE[issue] for issue in issue_codes],
        )


def _score_completeness(
    draft: TravelPlan,
    requirements: TripRequirements,
    search_summary: SearchSummary,
    tool_errors: Sequence[SearchErrorEnvelope],
    issues: set[ReviewIssueCode],
) -> float:
    """Score required content and honest non-critical data disclosure."""

    score = 100.0
    if getattr(draft, "flight", None) is None:
        score -= 25
        issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)
    if getattr(draft, "hotel", None) is None:
        score -= 25
        issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)

    itinerary = getattr(draft, "daily_itinerary", [])
    expected_dates = _expected_dates(requirements)
    actual_dates = [day.date for day in itinerary]
    if not itinerary:
        score -= 30
        issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)
    elif actual_dates != expected_dates:
        score -= 20
        issues.update(
            {
                ReviewIssueCode.MISSING_REQUIRED_CONTENT,
                ReviewIssueCode.INCONSISTENT_DATES,
            }
        )

    total_cost = getattr(draft, "total_cost", None)
    if not isinstance(total_cost, Decimal) or total_cost <= 0:
        score -= 20
        issues.update(
            {
                ReviewIssueCode.MISSING_REQUIRED_CONTENT,
                ReviewIssueCode.INVALID_COST_BREAKDOWN,
            }
        )

    unavailable_kinds = {
        kind for kind, summary in search_summary.items() if summary["status"] == "error"
    } | {error["kind"] for error in tool_errors}
    if unavailable_kinds:
        score -= 10
        issues.add(ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE)
        markdown = getattr(draft, "markdown", "").casefold()
        undisclosed = [
            kind
            for kind in unavailable_kinds
            if kind.casefold() not in markdown or "unavailable" not in markdown
        ]
        if undisclosed:
            score -= 10
            issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)
    return max(0.0, score)


def _score_feasibility(
    draft: TravelPlan,
    requirements: TripRequirements,
    issues: set[ReviewIssueCode],
) -> float:
    """Score date, route, daily pace, and basic cost consistency."""

    score = 100.0
    itinerary = getattr(draft, "daily_itinerary", [])
    expected_dates = _expected_dates(requirements)
    if [day.date for day in itinerary] != expected_dates or [
        day.day_number for day in itinerary
    ] != list(range(1, len(expected_dates) + 1)):
        score -= 30
        issues.add(ReviewIssueCode.INCONSISTENT_DATES)

    if any(_optional_visit_count(day.activities) > 2 for day in itinerary):
        score -= 25
        issues.add(ReviewIssueCode.ITINERARY_TOO_DENSE)

    total_cost = getattr(draft, "total_cost", None)
    if (
        not isinstance(total_cost, Decimal)
        or total_cost <= 0
        or any(day.estimated_cost < 0 for day in itinerary)
    ):
        score -= 25
        issues.add(ReviewIssueCode.INVALID_COST_BREAKDOWN)

    flight = getattr(draft, "flight", None)
    if (
        flight is None
        or flight.origin != requirements.origin
        or flight.destination != requirements.destination
    ):
        score -= 20
        issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)

    hotel = getattr(draft, "hotel", None)
    if hotel is None or hotel.city != requirements.destination:
        score -= 15
        issues.add(ReviewIssueCode.MISSING_REQUIRED_CONTENT)
    return max(0.0, score)


def _score_personalization(
    draft: TravelPlan,
    requirements: TripRequirements,
    retrieved_context: Sequence[str],
    remembered_preferences: Sequence[str],
    issues: set[ReviewIssueCode],
) -> float:
    """Score preference evidence; users without preferences receive a neutral 100."""

    preferences = _unique_nonempty([*requirements.preferences, *remembered_preferences])
    if not preferences:
        return 100.0

    activity_text = " ".join(
        activity for day in getattr(draft, "daily_itinerary", []) for activity in day.activities
    )
    markdown = getattr(draft, "markdown", "").split("## Remembered preferences", maxsplit=1)[0]
    evidence = " ".join([activity_text, markdown, *retrieved_context])
    reflected = sum(_preference_reflected(preference, evidence) for preference in preferences)
    score = round(100 * reflected / len(preferences), 2)
    if reflected < len(preferences):
        issues.add(ReviewIssueCode.PERSONALIZATION_MISSING)
    return score


def _score_budget_fit(
    draft: TravelPlan,
    requirements: TripRequirements,
    issues: set[ReviewIssueCode],
) -> float:
    """Score over-budget plans by the stable budget-to-total-cost percentage."""

    total_cost = getattr(draft, "total_cost", None)
    if not isinstance(total_cost, Decimal) or total_cost <= 0:
        issues.add(ReviewIssueCode.INVALID_COST_BREAKDOWN)
        return 0.0
    if total_cost <= requirements.budget:
        return 100.0
    issues.add(ReviewIssueCode.BUDGET_OVERRUN)
    return round(float(requirements.budget / total_cost * Decimal(100)), 2)


def _expected_dates(requirements: TripRequirements) -> list[date]:
    """Return the inclusive requested dates without using the current time."""

    day_count = (requirements.end_date - requirements.start_date).days + 1
    return [requirements.start_date + timedelta(days=offset) for offset in range(day_count)]


def _optional_visit_count(activities: Sequence[str]) -> int:
    """Count attraction visits without treating arrival or weather as optional stops."""

    return sum(activity.casefold().startswith("visit ") for activity in activities)


def _unique_nonempty(values: Sequence[str]) -> list[str]:
    """Normalize duplicate preferences while preserving deterministic input order."""

    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.casefold().split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _preference_reflected(preference: str, evidence: str) -> bool:
    """Require every meaningful preference token to appear in plan evidence."""

    evidence_tokens = {_stem(token) for token in re.findall(r"[a-z0-9]+", evidence.casefold())}
    preference_tokens = [_stem(token) for token in re.findall(r"[a-z0-9]+", preference.casefold())]
    return bool(preference_tokens) and all(token in evidence_tokens for token in preference_tokens)


def _stem(token: str) -> str:
    """Handle a simple English plural without introducing an NLP dependency."""

    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _build_critique(
    decision: ReviewDecision,
    issue_codes: Sequence[ReviewIssueCode],
    score_threshold: float,
) -> str:
    """Build stable human guidance from the same machine-readable issue list."""

    if not issue_codes:
        return f"Quality review passed the configured {score_threshold:.2f} threshold."
    details = " ".join(_CRITIQUE_BY_ISSUE[issue] for issue in issue_codes)
    if decision is ReviewDecision.ACCEPT:
        return f"Quality review passed with documented limitations. {details}"
    if decision is ReviewDecision.FORCED_FINALIZE:
        return f"Maximum review rounds reached. {details}"
    return details
