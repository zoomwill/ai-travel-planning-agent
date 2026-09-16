"""Process-only isolation for opt-in tests against the local Compose stack."""

from pytest import MonkeyPatch


def isolate_local_infrastructure(monkeypatch: MonkeyPatch) -> None:
    """Override remote targets and paid modes, retaining local Compose credentials/ports."""
    overrides = {
        "APP_ENV": "test",
        "AUTH_MODE": "demo",
        "AGENT_REASONING_MODE": "deterministic",
        "TRAVEL_DATA_MODE": "demo",
        "TRAVEL_SEARCH_BACKEND_MODE": "direct",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_SSLMODE": "disable",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_SSL": "false",
        "CHROMA_HOST": "127.0.0.1",
        "CHROMA_SSL": "false",
        "MCP_HTTP_URL": "",
        "QWEN_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "DUFFEL_ACCESS_TOKEN": "",
        "LITEAPI_API_KEY": "",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
        "TRUSTED_HOSTS": '["127.0.0.1", "localhost", "testserver"]',
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
