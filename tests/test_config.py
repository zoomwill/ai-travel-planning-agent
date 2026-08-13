"""Tests for typed settings and secret handling."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_postgres_url_safely_handles_special_characters() -> None:
    password = "not-real:p@ss/word?#%"
    settings = Settings(_env_file=None, postgres_password=SecretStr(password))

    assert settings.postgres_url.password == password
    assert password not in str(settings.postgres_url)
    assert "%40" in settings.postgres_url.render_as_string(hide_password=False)


def test_settings_and_url_representations_redact_password() -> None:
    password = "not-a-real-secret"
    settings = Settings(_env_file=None, postgres_password=SecretStr(password))

    assert password not in repr(settings)
    assert password not in str(settings)
    assert password not in repr(settings.postgres_url)
    assert password not in str(settings.postgres_url)


def test_langgraph_uri_uses_official_scheme_and_remains_redacted() -> None:
    """LangGraph receives a safely encoded URI while ordinary output hides it."""

    password = "not-real:p@ss/word?#%"
    settings = Settings(_env_file=None, postgres_password=SecretStr(password))
    secret_uri = settings.langgraph_postgres_uri
    raw_uri = secret_uri.get_secret_value()

    assert raw_uri.startswith("postgresql://")
    assert "postgresql+psycopg" not in raw_uri
    assert "sslmode=disable" in raw_uri
    assert "%40" in raw_uri
    assert password not in str(secret_uri)
    assert password not in repr(secret_uri)


def test_infrastructure_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, infrastructure_timeout_seconds=0)


def test_review_defaults_are_bounded_and_recursion_limit_is_standalone_setting() -> None:
    """Local P09 defaults allow three reviews and a much larger graph safety limit."""

    settings = Settings(_env_file=None)

    assert settings.review_score_threshold == 80
    assert settings.review_max_rounds == 3
    assert settings.graph_recursion_limit == 50


@pytest.mark.parametrize("threshold", [-0.01, 100.01])
def test_review_threshold_stays_on_zero_to_one_hundred_scale(threshold: float) -> None:
    """A threshold outside the QualityScore scale is rejected before graph execution."""

    with pytest.raises(ValidationError):
        Settings(_env_file=None, review_score_threshold=threshold)


@pytest.mark.parametrize(
    ("field", "value"),
    [("review_max_rounds", 0), ("graph_recursion_limit", 0)],
)
def test_review_round_and_recursion_limits_must_be_positive(
    field: str,
    value: int,
) -> None:
    """Neither business loop safety setting accepts zero."""

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
