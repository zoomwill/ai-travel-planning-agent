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
    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    auth_mode: Literal["demo", "auth0"] = "demo"
    auth0_issuer: str = ""
    auth0_audience: str = Field(default="", max_length=256)
    auth_jwks_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_jwks_timeout_seconds: float = Field(default=5, gt=0, le=15)
    auth_rate_intake_per_minute: int = Field(default=10, ge=1, le=100)
    auth_rate_intake_per_day: int = Field(default=50, ge=1, le=1000)
    auth_rate_global_intake_per_day: int = Field(default=200, ge=1, le=5000)
    auth_rate_plan_per_day: int = Field(default=3, ge=1, le=100)
    auth_rate_global_plan_per_day: int = Field(default=20, ge=1, le=1000)
    api_docs_enabled: bool = True
    metrics_enabled: bool = True
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "testserver"]
    )

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
    redis_username: str | None = None
    redis_password: SecretStr = SecretStr("")
    redis_ssl: bool = False

    chroma_host: str = "127.0.0.1"
    chroma_port: int = Field(default=8001, ge=1, le=65535)
    chroma_ssl: bool = False

    infrastructure_timeout_seconds: float = Field(default=2.0, gt=0)

    travel_data_mode: Literal["demo", "external", "duffel"] = "demo"
    travel_flight_provider: Literal["demo", "duffel"] = "duffel"
    travel_hotel_provider: Literal["demo", "liteapi", "duffel_stays"] = "liteapi"
    liteapi_env: Literal["sandbox", "production"] = "sandbox"
    liteapi_api_key: SecretStr = SecretStr("")
    liteapi_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    liteapi_max_retries: int = Field(default=1, ge=0, le=2)
    liteapi_max_hotels: int = Field(default=10, ge=1, le=20)
    liteapi_max_rates_per_hotel: int = Field(default=1, ge=1, le=20)
    liteapi_allow_demo_fallback: bool = False
    duffel_env: Literal["test", "live"] = "test"
    duffel_access_token: SecretStr = SecretStr("")
    duffel_api_base_url: Literal["https://api.duffel.com"] = "https://api.duffel.com"
    duffel_api_version: Literal["v2"] = "v2"
    duffel_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    duffel_max_retries: int = Field(default=1, ge=0, le=3)
    duffel_max_flight_offers: int = Field(default=5, ge=1, le=20)
    duffel_max_stay_results: int = Field(default=10, ge=1, le=50)
    duffel_allow_demo_fallback: bool = False

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
    intake_history_limit: int = Field(default=30, ge=2, le=100)

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
    rag_embedding_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    rag_embedding_normalize: bool = True
    rag_bootstrap_batch_size: int = Field(default=8, ge=1, le=32)
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
        hide_input_in_errors=True,
    )

    @field_validator("rag_bootstrap_batch_size", mode="before")
    @classmethod
    def validate_bootstrap_batch_integer(cls, value: object) -> object:
        """Allow integer environment strings but not boolean or floating-point batch sizes."""

        if isinstance(value, (bool, float)):
            raise ValueError("bootstrap batch size must be an integer")
        return value

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        """Fail closed for unsafe cloud configuration while preserving local demo defaults."""

        import re

        from app.auth.configuration import https_origin, normalize_issuer

        if self.auth0_issuer:
            self.auth0_issuer = normalize_issuer(self.auth0_issuer)
        if self.auth_mode == "auth0" and (not self.auth0_issuer or not self.auth0_audience.strip()):
            raise ValueError("auth0 mode requires issuer and API audience")
        for origin in self.cors_allowed_origins:
            if origin not in ("http://127.0.0.1:5173", "http://localhost:5173"):
                if https_origin(origin) != origin:
                    raise ValueError("CORS must contain exact origins without trailing slash")
        if not self.trusted_hosts or any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host) is None
            for host in self.trusted_hosts
        ):
            raise ValueError("trusted hosts must be explicit hostnames without wildcards")
        if self.app_env == "production":
            if self.auth_mode != "auth0" or self.api_docs_enabled or self.metrics_enabled:
                raise ValueError("production requires auth0 and disabled public docs/metrics")
            if not self.cors_allowed_origins or any(
                not origin.startswith("https://") for origin in self.cors_allowed_origins
            ):
                raise ValueError("production requires explicit HTTPS frontend origins")
            if not any(
                "." in host and host != "healthcheck.railway.app" and host != "127.0.0.1"
                for host in self.trusted_hosts
            ):
                raise ValueError("production requires the actual API hostname")
            if self.postgres_password.get_secret_value() in ("", "travel_dev_only"):
                raise ValueError("production requires a non-development database password")
            if not self.redis_password.get_secret_value():
                raise ValueError("production requires Redis authentication")
            if self.external_configuration_error is not None:
                raise ValueError("selected external travel providers require credentials")
            if self.agent_reasoning_mode == "qwen" and not self.qwen_is_configured:
                raise ValueError("Qwen mode requires its backend credential")
            if self.travel_search_backend_mode != "direct":
                raise ValueError("P18 cloud deployment supports the direct backend only")
        return self

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
        token = self.duffel_access_token.get_secret_value()
        if token and self.duffel_env == "test" and not token.startswith("duffel_test_"):
            raise ValueError("duffel_env=test requires a Duffel test access token")
        if token and self.duffel_env == "live" and token.startswith("duffel_test_"):
            raise ValueError("duffel_env=live cannot use a Duffel test access token")
        hotel_key = self.liteapi_api_key.get_secret_value()
        if hotel_key:
            valid_prefixes = ("sand_", "sandbox_") if self.liteapi_env == "sandbox" else ("prod_",)
            if not hotel_key.startswith(valid_prefixes):
                raise ValueError("LiteAPI key must match its explicitly configured environment")
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
    def duffel_is_configured(self) -> bool:
        """Report access-token presence without exposing token content or prefix."""

        return bool(self.duffel_access_token.get_secret_value())

    @property
    def selected_flight_provider(self) -> Literal["demo", "duffel"]:
        """Keep legacy Duffel mode explicit; demo overrides all selectors."""

        if self.travel_data_mode == "demo":
            return "demo"
        return "duffel" if self.travel_data_mode == "duffel" else self.travel_flight_provider

    @property
    def selected_hotel_provider(self) -> Literal["demo", "liteapi", "duffel_stays"]:
        """Select LiteAPI only in the new external mode, never through the legacy alias."""

        if self.travel_data_mode == "demo":
            return "demo"
        return "duffel_stays" if self.travel_data_mode == "duffel" else self.travel_hotel_provider

    @property
    def liteapi_is_configured(self) -> bool:
        """Report presence only, with no key-derived public information."""

        return bool(self.liteapi_api_key.get_secret_value().strip())

    @property
    def needs_duffel(self) -> bool:
        """Duffel also supplies the shared authoritative city/airport resolver."""

        return self.selected_flight_provider == "duffel" or self.selected_hotel_provider != "demo"

    @property
    def requires_guest_nationality(self) -> bool:
        """Apply hotel-pricing intake policy deterministically."""

        return self.selected_hotel_provider == "liteapi"

    @property
    def external_configuration_error(self) -> str | None:
        """Check credentials locally without any provider searches."""

        if self.needs_duffel and not self.duffel_is_configured:
            return "duffel_not_configured"
        if self.requires_guest_nationality and not self.liteapi_is_configured:
            return "liteapi_not_configured"
        return None

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
