"""Safe local-development API schemas for P10 advanced retrieval."""

from pydantic import BaseModel, ConfigDict, Field

from app.rag.models import RetrievalDiagnostics


class RagSearchRequest(BaseModel):
    """One validated direct retrieval request."""

    query: str = Field(min_length=1, max_length=2000)
    destination: str | None = Field(default=None, min_length=1, max_length=100)
    preferences: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=4, ge=1, le=8)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RagSearchResponse(BaseModel):
    """Final parent contexts without vectors, cache keys, or client details."""

    contexts: list[str]
    parent_ids: list[str]
    diagnostics: RetrievalDiagnostics


class RagStatusResponse(BaseModel):
    """Bounded non-secret status for a local prepared advanced index."""

    pipeline_version: str
    indexed: bool
    collection_name: str
    child_count: int = Field(ge=0)
    parent_count: int = Field(ge=0)
    corpus_fingerprint: str
    embedding_model: str
    embedding_dimension: int = Field(ge=0)
    bm25_ready: bool
    cache_available: bool
