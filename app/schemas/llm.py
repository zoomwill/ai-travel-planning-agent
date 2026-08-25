"""Safe public models for optional LLM runtime status."""

from typing import Literal

from pydantic import BaseModel


class LLMStatusResponse(BaseModel):
    """Expose configuration state without credentials or client objects."""

    reasoning_mode: Literal["deterministic", "qwen"]
    provider: Literal["none", "qwen"]
    configured: bool
    model: str
    base_url_region_or_host_class: str
    fallback_enabled: bool
