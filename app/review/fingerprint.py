"""Stable SHA-256 fingerprints for complete structured travel-plan drafts."""

import hashlib
import json

from app.domain.models import TravelPlan


def create_draft_fingerprint(plan: TravelPlan) -> str:
    """Hash canonical JSON for every TravelPlan field, including Markdown."""

    canonical_plan = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_plan.encode("utf-8")).hexdigest()
