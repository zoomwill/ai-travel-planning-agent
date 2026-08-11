"""Validated request and response models for P07 persistence APIs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import TravelPlan, TripRequirements

PreferenceText = Annotated[str, Field(min_length=1, max_length=200)]


class ThreadPlanRequest(BaseModel):
    """A trip request plus explicit long-term-memory instructions."""

    user_id: str
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
    travel_plan: TravelPlan
    remembered_preferences: list[str]


class ThreadStateResponse(BaseModel):
    """A filtered latest checkpoint that omits internal LangGraph metadata."""

    thread_id: str
    status: Literal["empty", "running", "complete", "error"]
    user_request: str | None = None
    next_agent: str | None = None
    remembered_preferences: list[str] = Field(default_factory=list)
    travel_plan: TravelPlan | None = None
    error: str | None = None


class ThreadHistoryItem(BaseModel):
    """A safe summary of one checkpoint in newest-first order."""

    checkpoint_id: str
    created_at: datetime
    next: list[str]
    tasks: list[str]
    status: Literal["empty", "running", "complete", "error"]


class ThreadHistoryResponse(BaseModel):
    """A bounded list of checkpoint summaries for one thread."""

    thread_id: str
    checkpoints: list[ThreadHistoryItem]
