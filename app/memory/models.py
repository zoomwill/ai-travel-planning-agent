"""Typed records stored as explicit long-term user preference memory."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PreferenceCategory(StrEnum):
    """Small deterministic vocabulary for saved travel preferences."""

    INTEREST = "interest"
    PACE = "pace"
    CROWD_PREFERENCE = "crowd_preference"
    FOOD = "food"
    ACCOMMODATION = "accommodation"
    TRANSPORT = "transport"
    GENERAL = "general"


class PreferenceMemory(BaseModel):
    """One user-approved preference stored across independent trip threads."""

    preference_id: str = Field(min_length=1)
    value: str = Field(min_length=1)
    normalized_value: str = Field(min_length=1)
    category: PreferenceCategory
    source_thread_id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
