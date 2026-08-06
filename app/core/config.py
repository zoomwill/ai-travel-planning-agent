"""Application settings for the starter repository."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal settings used before infrastructure phases are implemented."""

    app_name: str = "ai-travel-planner"
    app_env: str = "development"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings object."""

    return Settings()
