"""Project persisted review metadata without running the graph or rewriting history."""

from collections.abc import Mapping

from pydantic import ValidationError

from app.domain.models import TravelPlan
from app.domain.quality import PlanQuality, PlanWarning
from app.review.models import PlanReview, ReviewDecision


def present_plan(
    plan: TravelPlan, state: Mapping[str, object], *, historical: bool = True
) -> TravelPlan:
    """Attach bounded quality information using trusted application review fields."""

    quality = PlanQuality()
    try:
        review = PlanReview.model_validate(state.get("current_review"))
        status = state.get("review_status")
        reason = state.get("finalization_reason")
        consistent = (
            status == "accepted"
            and reason == "threshold_reached"
            and review.decision is ReviewDecision.ACCEPT
        ) or (
            status == "forced_finalized"
            and reason == "max_review_rounds_reached"
            and review.decision is ReviewDecision.FORCED_FINALIZE
        )
        if (
            consistent
            and not state.get("error")
            and review.review_round == state.get("review_round")
        ):
            quality = PlanQuality.model_validate(
                {
                    "review_status": status,
                    "review_rounds": review.review_round,
                    "final_score": review.scores.overall_score,
                    "finalization_reason": reason,
                    "issue_codes": sorted(set(review.issue_codes)),
                }
            )
    except (ValidationError, TypeError, ValueError):
        # Missing historical review is unknown, never inferred from score/text.
        pass
    warnings = list(plan.warnings)
    if historical and PlanWarning.ROUTE_UNAVAILABLE not in warnings:
        warnings.append(PlanWarning.HISTORICAL_ROUTE_UNVERIFIED)
    warnings.append(PlanWarning.RETURN_FLIGHT_EXCLUDED)
    if plan.hotel.has_excluded_fees:
        warnings.append(PlanWarning.EXCLUDED_HOTEL_FEES)
    return plan.model_copy(update={"quality": quality, "warnings": list(dict.fromkeys(warnings))})
