"""Strict JSON-safe models shared by the P10 advanced RAG pipeline."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CacheStatus = Literal["hit", "miss", "disabled", "unavailable", "corrupt"]
RetrievalMethod = Literal["dense", "sparse"]
RetrievalMode = Literal["dense_only", "bm25_only", "hybrid_rrf", "hybrid_reranked"]


class RagModel(BaseModel):
    """Reject unknown fields and normalize surrounding whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class ParentDocument(RagModel):
    """A larger Markdown section returned to Planner as complete context."""

    parent_id: str = Field(min_length=64, max_length=64)
    source: str = Field(min_length=1)
    city: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    index_version: str = Field(min_length=1)


class ChildChunk(RagModel):
    """A small searchable passage that always points to one parent document."""

    child_id: str = Field(min_length=64, max_length=64)
    parent_id: str = Field(min_length=64, max_length=64)
    source: str = Field(min_length=1)
    city: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=16)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    index_version: str = Field(min_length=1)


class QueryBundle(RagModel):
    """Validated request information used to construct deterministic query variants."""

    original_query: str = Field(min_length=1, max_length=2000)
    query_variants: list[str] = Field(default_factory=list, max_length=8)
    destination: str | None = Field(default=None, max_length=100)
    current_preferences: list[str] = Field(default_factory=list, max_length=50)
    remembered_preferences: list[str] = Field(default_factory=list, max_length=50)
    metadata_filter: dict[str, str] = Field(default_factory=dict)


class RetrievalCandidate(RagModel):
    """One child result from exactly one dense or sparse ranking."""

    child_id: str
    parent_id: str
    source: str
    city: str
    content: str
    retrieval_method: RetrievalMethod
    query_variant: str
    rank: int = Field(ge=1)
    raw_score: float


class FusedCandidate(RagModel):
    """One child after rank-only Reciprocal Rank Fusion."""

    child_id: str
    parent_id: str
    rrf_score: float = Field(ge=0)
    dense_ranks: list[int] = Field(default_factory=list)
    sparse_ranks: list[int] = Field(default_factory=list)
    matched_variants: list[str] = Field(default_factory=list)
    retrieval_sources: list[str] = Field(default_factory=list)


class RerankedParent(RagModel):
    """A complete parent document after transparent feature reranking."""

    parent_id: str
    source: str
    city: str
    title: str
    content: str
    rrf_score: float = Field(ge=0)
    rerank_score: float = Field(ge=0)
    matched_preferences: list[str] = Field(default_factory=list)
    matched_query_terms: list[str] = Field(default_factory=list)


class RetrievalDiagnostics(RagModel):
    """Bounded operational facts safe for API responses and checkpoints."""

    pipeline_version: str
    corpus_fingerprint: str
    embedding_backend: str
    embedding_model: str
    query_variant_count: int = Field(ge=0)
    dense_candidate_count: int = Field(ge=0)
    sparse_candidate_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    reranked_candidate_count: int = Field(ge=0)
    returned_parent_count: int = Field(ge=0)
    metadata_filter_applied: bool
    metadata_filter_fallback_used: bool
    cache_status: CacheStatus
    degraded_components: list[str] = Field(default_factory=list)
    missing_parent_count: int = Field(default=0, ge=0)


class AdvancedRetrievalResult(RagModel):
    """Final parent-level contexts and their safe diagnostics."""

    contexts: list[str]
    parent_ids: list[str]
    query_variants: list[str] = Field(default_factory=list, max_length=8)
    diagnostics: RetrievalDiagnostics
    error: str | None = None


class RagIndexManifest(RagModel):
    """Reproducible description of one locally generated advanced index."""

    pipeline_version: str
    collection_name: str
    corpus_fingerprint: str = Field(min_length=64, max_length=64)
    embedding_backend: str
    embedding_model: str
    embedding_dimension: int = Field(gt=0)
    parent_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
