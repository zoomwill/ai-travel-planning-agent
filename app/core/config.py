"""Type-safe application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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

    travel_search_backend_mode: Literal["direct", "mcp"] = "direct"
    mcp_http_host: Literal["127.0.0.1"] = "127.0.0.1"
    mcp_http_port: int = Field(default=9001, ge=1, le=65535)
    mcp_http_path: str = Field(default="/mcp", pattern=r"^/[A-Za-z0-9._~/-]+$")
    mcp_http_url: str = ""
    mcp_tool_timeout_seconds: float = Field(default=8.0, gt=0)
    mcp_discovery_timeout_seconds: float = Field(default=15.0, gt=0)
    mcp_max_retries: int = Field(default=1, ge=0, le=3)
    mcp_require_all_tools: bool = True
    mcp_enable_stdio_server: bool = True
    mcp_enable_http_server: bool = True

    review_score_threshold: float = Field(default=80.0, ge=0, le=100)
    review_max_rounds: int = Field(default=3, ge=1)
    graph_recursion_limit: int = Field(default=50, ge=1)
    sse_heartbeat_seconds: float = Field(default=10.0, gt=0, le=14.0)
    sse_queue_maxsize: int = Field(default=64, ge=1, le=1024)

    agent_reasoning_mode: Literal["deterministic", "qwen"] = "deterministic"
    qwen_model: str = Field(
        default="qwen-plus",
        min_length=1,
        max_length=128,
        pattern=r"^qwen[A-Za-z0-9._/-]{0,124}$",
    )
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "qwen_api_key",
            "QWEN_API_KEY",
            "DASHSCOPE_API_KEY",
        ),
    )
    qwen_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    qwen_max_retries: int = Field(default=1, ge=0, le=2)
    qwen_max_completion_tokens: int = Field(default=2048, ge=256, le=4096)
    qwen_temperature: float = Field(default=0.2, ge=0, le=0.2)
    qwen_enable_thinking: bool = False
    qwen_allow_deterministic_fallback: bool = False

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

    @field_validator("qwen_model", mode="before")
    @classmethod
    def default_empty_qwen_model(cls, value: object) -> object:
        """Treat the pre-P14 template's empty value as the documented safe default."""

        return "qwen-plus" if value == "" else value

    @field_validator("qwen_base_url", mode="before")
    @classmethod
    def default_empty_qwen_base_url(cls, value: object) -> object:
        """Normalize the pre-P14 blank endpoint to the official Beijing endpoint."""

        if value == "":
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return value

    @model_validator(mode="after")
    def validate_rag_relationships(self) -> "Settings":
        """Reject settings that would create invalid RAG or local MCP behavior."""

        if self.rag_parent_chunk_overlap >= self.rag_parent_chunk_size:
            raise ValueError("rag_parent_chunk_overlap must be smaller than parent chunk size")
        if self.rag_child_chunk_overlap >= self.rag_child_chunk_size:
            raise ValueError("rag_child_chunk_overlap must be smaller than child chunk size")
        if self.rag_final_parent_k > self.rag_rerank_top_k:
            raise ValueError("rag_final_parent_k cannot exceed rag_rerank_top_k")
        from app.llm.configuration import validate_qwen_base_url
        from app.llm.errors import LLMError

        try:
            validate_qwen_base_url(self.qwen_base_url)
        except LLMError:
            raise ValueError(
                "qwen_base_url must be an official HTTPS Model Studio endpoint"
            ) from None
        if self.qwen_enable_thinking:
            raise ValueError("qwen_enable_thinking must remain false for P14 JSON tasks")
        expected_mcp_url = f"http://{self.mcp_http_host}:{self.mcp_http_port}{self.mcp_http_path}"
        if not self.mcp_http_url:
            self.mcp_http_url = expected_mcp_url
        parsed_mcp_url = urlsplit(self.mcp_http_url)
        if (
            parsed_mcp_url.scheme != "http"
            or parsed_mcp_url.hostname != self.mcp_http_host
            or parsed_mcp_url.port != self.mcp_http_port
            or parsed_mcp_url.path != self.mcp_http_path
            or parsed_mcp_url.username is not None
            or parsed_mcp_url.password is not None
            or parsed_mcp_url.query
            or parsed_mcp_url.fragment
        ):
            raise ValueError(
                "mcp_http_url must exactly match the configured local host, port, and path"
            )
        return self

    @property
    def qwen_is_configured(self) -> bool:
        """Report key presence without exposing the key value."""

        return bool(self.qwen_api_key.get_secret_value())

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
