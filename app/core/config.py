"""Type-safe application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
