"""Configuration, endpoint allowlist, and lifecycle tests."""

from typing import cast

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.llm.configuration import validate_qwen_base_url
from app.llm.errors import LLMError
from app.llm.runtime import create_llm_runtime


@pytest.mark.parametrize(
    ("url", "host_class"),
    [
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "china-beijing",
        ),
        (
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "singapore",
        ),
        (
            "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            "united-states",
        ),
        (
            "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
            "china-hong-kong",
        ),
        (
            "https://trial.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
            "workspace-ap-southeast-1",
        ),
    ],
)
def test_official_qwen_endpoints_are_allowlisted(url: str, host_class: str) -> None:
    assert validate_qwen_base_url(url) == host_class


@pytest.mark.parametrize(
    "url",
    [
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://localhost/compatible-mode/v1",
        "https://127.0.0.1/compatible-mode/v1",
        "https://example.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1",
        "https://dashscope.aliyuncs.com/v1",
        "https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com:443/compatible-mode/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1?target=evil.example",
        "https://dashscope.aliyuncs.com/compatible-mode/v1#evil",
        "https://dashscope.aliyuncs.com./compatible-mode/v1",
        "https://trial.ap-southeast-2.maas.aliyuncs.com/compatible-mode/v1",
        "https://trial.ap-southeast-1.maas.aliyuncs.com.evil/compatible-mode/v1",
    ],
)
def test_unofficial_or_malicious_qwen_endpoints_are_rejected(url: str) -> None:
    with pytest.raises(LLMError, match="llm_invalid_base_url"):
        validate_qwen_base_url(url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, qwen_base_url=url)


def test_deterministic_mode_never_initializes_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(**_: object) -> None:
        raise AssertionError("deterministic mode initialized Qwen")

    monkeypatch.setattr("app.llm.runtime.AsyncOpenAI", unexpected_client)
    runtime = create_llm_runtime(Settings(_env_file=None))

    assert runtime.provider is None
    assert runtime.diagnostics.reasoning_mode == "deterministic"
    assert runtime.diagnostics.configured is False


def test_qwen_mode_without_key_stays_unconfigured_but_does_not_crash() -> None:
    runtime = create_llm_runtime(
        Settings(
            _env_file=None,
            agent_reasoning_mode="qwen",
            qwen_api_key=SecretStr(""),
        )
    )

    assert runtime.provider is None
    assert runtime.diagnostics.initialization_error == "llm_not_configured"


@pytest.mark.asyncio
async def test_qwen_runtime_owns_one_reused_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class ClientDouble:
        async def close(self) -> None:
            return None

    def client_factory(**_: object) -> object:
        client = ClientDouble()
        created.append(client)
        return client

    monkeypatch.setattr("app.llm.runtime.AsyncOpenAI", client_factory)
    runtime = create_llm_runtime(
        Settings(
            _env_file=None,
            agent_reasoning_mode="qwen",
            qwen_api_key=SecretStr("not-a-real-key"),
        )
    )

    assert len(created) == 1
    assert runtime.provider is not None
    assert cast(object, runtime.provider)._client is created[0]
    assert cast(object, runtime.provider)._max_completion_tokens == 2048
    await runtime.aclose()


def test_api_key_remains_redacted_in_settings() -> None:
    key = "not-a-real-qwen-secret"
    settings = Settings(_env_file=None, qwen_api_key=SecretStr(key))

    assert key not in repr(settings)
    assert key not in str(settings)


def test_dashscope_api_key_alias_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    alias_key = "not-a-real-dashscope-key"
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", alias_key)

    settings = Settings(_env_file=None)

    assert settings.qwen_is_configured is True
    assert alias_key not in repr(settings)


@pytest.mark.parametrize("value", [255, 4097])
def test_qwen_completion_limit_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, qwen_max_completion_tokens=value)


@pytest.mark.parametrize(
    "model",
    ["sk-not-a-real-api-key", "gpt-4", "qwen-plus\nAuthorization: hidden"],
)
def test_qwen_model_name_cannot_carry_a_secret_or_control_text(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, qwen_model=model)
