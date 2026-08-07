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


def test_infrastructure_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, infrastructure_timeout_seconds=0)
