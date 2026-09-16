"""Validated request and response models for P07 persistence APIs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import TravelPlan, TripRequirements
from app.domain.quality import PlanQuality, PlanWarning
from app.rag.models import RetrievalDiagnostics
from app.review.models import FinalizationReason, PlanReview, ReviewStatus
from app.search.models import SearchErrorEnvelope, SearchSummary

PreferenceText = Annotated[str, Field(min_length=1, max_length=200)]


class ThreadPlanRequest(BaseModel):
    """A trip request plus explicit long-term-memory instructions."""

    user_id: str | None = None
    requirements: TripRequirements
    remember_preferences: list[PreferenceText] = Field(
        default_factory=list,
        max_length=50,
    )

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ThreadPlanResponse(BaseModel):
    """The persistent thread result returned to the caller."""

    thread_id: str
    user_id: str
    search_backend_mode: Literal["direct", "mcp"] = "direct"
    travel_plan: TravelPlan
    remembered_preferences: list[str]
    search_summary: SearchSummary = Field(default_factory=dict)
    tool_errors: list[SearchErrorEnvelope] = Field(default_factory=list)
    review_status: ReviewStatus
    review_rounds: int = Field(ge=0)
    final_score: float | None = Field(default=None, ge=0, le=100)
    finalization_reason: FinalizationReason | None = None
    review_summary: PlanReview | None = None
    retrieval_query_variants: list[str] = Field(default_factory=list)
    retrieval_parent_ids: list[str] = Field(default_factory=list)
    retrieval_diagnostics: RetrievalDiagnostics | None = None
    retrieval_error: str | None = None


class ThreadStateResponse(BaseModel):
    """A filtered latest checkpoint that omits internal LangGraph metadata."""

    thread_id: str
    status: Literal["empty", "running", "complete", "error"]
    search_backend_mode: Literal["direct", "mcp"] = "direct"
    user_request: str | None = None
    next_agent: str | None = None
    remembered_preferences: list[str] = Field(default_factory=list)
    search_summary: SearchSummary = Field(default_factory=dict)
    search_result_count: int = Field(default=0, ge=0)
    tool_error_count: int = Field(default=0, ge=0)
    review_status: ReviewStatus = "pending"
    review_round: int = Field(default=0, ge=0)
    final_score: float | None = Field(default=None, ge=0, le=100)
    finalization_reason: FinalizationReason | None = None
    draft_present: bool = False
    review_history_count: int = Field(default=0, ge=0)
    retrieval_query_variant_count: int = Field(default=0, ge=0)
    retrieval_parent_ids: list[str] = Field(default_factory=list)
    retrieval_diagnostics: RetrievalDiagnostics | None = None
    retrieval_error: str | None = None
    travel_plan: TravelPlan | None = None
    error: str | None = None


class ThreadHistoryItem(BaseModel):
    """A safe summary of one checkpoint in newest-first order."""

    checkpoint_id: str
    quality: PlanQuality | None = None
    warnings: list[PlanWarning] = Field(default_factory=list, max_length=6)
    created_at: datetime
    next: list[str]
    tasks: list[str]
    status: Literal["empty", "running", "complete", "error"]


class ThreadHistoryResponse(BaseModel):
    """A bounded list of checkpoint summaries for one thread."""

    thread_id: str
    checkpoints: list[ThreadHistoryItem]
