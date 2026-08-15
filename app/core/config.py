"""Type-safe application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validate application and local infrastructure configuration."""

    app_name: str = "ai-travel-planner"
    app_env: str = "development"
    log_level: str = "INFO"

    postgres_user: str = "travel"
    postgres_password: SecretStr = SecretStr("travel_dev_only")
    postgres_db: str = "travel_planner"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_sslmode: Literal[
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    ] = "disable"

    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)

    chroma_host: str = "127.0.0.1"
    chroma_port: int = Field(default=8001, ge=1, le=65535)
    chroma_ssl: bool = False

    infrastructure_timeout_seconds: float = Field(default=2.0, gt=0)

    review_score_threshold: float = Field(default=80.0, ge=0, le=100)
    review_max_rounds: int = Field(default=3, ge=1)
    graph_recursion_limit: int = Field(default=50, ge=1)

    rag_pipeline_version: str = Field(default="advanced-v1", min_length=1, max_length=64)
    rag_child_collection: str = Field(
        default="travel_knowledge_children_v1",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]$",
    )
    rag_embedding_backend: Literal["sentence_transformers"] = "sentence_transformers"
    rag_embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        min_length=1,
        max_length=256,
    )
    rag_embedding_device: str = Field(default="cpu", min_length=1, max_length=32)
    rag_embedding_normalize: bool = True
    rag_parent_chunk_size: int = Field(default=1200, gt=0)
    rag_parent_chunk_overlap: int = Field(default=150, ge=0)
    rag_child_chunk_size: int = Field(default=350, gt=0)
    rag_child_chunk_overlap: int = Field(default=50, ge=0)
    rag_query_variant_count: int = Field(default=4, ge=1, le=8)
    rag_dense_top_k: int = Field(default=20, gt=0)
    rag_sparse_top_k: int = Field(default=20, gt=0)
    rag_fusion_top_k: int = Field(default=20, gt=0)
    rag_rerank_top_k: int = Field(default=8, gt=0)
    rag_final_parent_k: int = Field(default=4, gt=0)
    rag_rrf_k: int = Field(default=60, gt=0)
    rag_cache_ttl_seconds: int = Field(default=3600, gt=0)
    rag_enable_cache: bool = True
    rag_metadata_filter_fallback: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_rag_relationships(self) -> "Settings":
        """Reject RAG settings that would create invalid windows or result limits."""

        if self.rag_parent_chunk_overlap >= self.rag_parent_chunk_size:
            raise ValueError("rag_parent_chunk_overlap must be smaller than parent chunk size")
        if self.rag_child_chunk_overlap >= self.rag_child_chunk_size:
            raise ValueError("rag_child_chunk_overlap must be smaller than child chunk size")
        if self.rag_final_parent_k > self.rag_rerank_top_k:
            raise ValueError("rag_final_parent_k cannot exceed rag_rerank_top_k")
        return self

    @property
    def postgres_url(self) -> URL:
        """Build a PostgreSQL URL without unsafe string concatenation."""

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def langgraph_postgres_uri(self) -> SecretStr:
        """Build the official PostgreSQL URI expected by LangGraph connectors."""

        uri = URL.create(
            drivername="postgresql",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
            query={"sslmode": self.postgres_sslmode},
        )
        return SecretStr(uri.render_as_string(hide_password=False))


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings object."""

    return Settings()
