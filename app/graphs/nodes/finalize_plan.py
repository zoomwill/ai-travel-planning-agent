"""Finalize the last reviewed draft without querying or scoring again."""

from app.domain.models import TravelPlan
from app.graphs.state import TravelPlanState


def finalize_plan_node(state: TravelPlanState) -> TravelPlanState:
    """Validate the draft, append an honest review outcome, and expose final TravelPlan."""

    draft_data = state.get("draft_plan")
    if draft_data is None:
        return {
            "travel_plan": None,
            "review_status": "failed",
            "error": "finalization_failed",
        }
    try:
        draft = TravelPlan.model_validate(draft_data)
    except Exception:
        return {
            "travel_plan": None,
            "review_status": "failed",
            "error": "finalization_failed",
        }

    reason = state.get("finalization_reason")
    if reason == "max_review_rounds_reached":
        outcome = "Quality review ended because the maximum review rounds were reached."
    elif reason == "threshold_reached":
        outcome = "Quality review passed the configured deterministic threshold."
    else:
        outcome = "Quality review could not complete; this draft is retained as a best-effort plan."
    markdown = "\n\n".join([draft.markdown, f"## Quality review\n- {outcome}"])
    final_plan = draft.model_copy(update={"markdown": markdown})
    return {"travel_plan": final_plan, "error": state.get("error")}
