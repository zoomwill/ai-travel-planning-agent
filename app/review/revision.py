"""Translate deterministic issue codes into executable Planner policy."""

from app.review.models import ReviewIssueCode, RevisionPolicy


def policy_for_issues(issue_codes: list[ReviewIssueCode]) -> RevisionPolicy:
    """Build one stable policy from the set of current review issues."""

    issues = set(issue_codes)
    return RevisionPolicy(
        prefer_lower_cost_options=ReviewIssueCode.BUDGET_OVERRUN in issues,
        max_activities_per_day=(1 if ReviewIssueCode.ITINERARY_TOO_DENSE in issues else None),
        prioritize_preferences=ReviewIssueCode.PERSONALIZATION_MISSING in issues,
        include_missing_data_notices=(ReviewIssueCode.NONCRITICAL_DATA_UNAVAILABLE in issues),
    )
