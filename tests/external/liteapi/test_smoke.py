"""The real checker must stop locally without its opt-in gate and credentials."""

from unittest.mock import Mock

import httpx
import pytest

from app.core.config import Settings
from app.domain.models import TravelDataSource
from scripts import check_liteapi
from tests.external.liteapi.helpers import FAKE_KEY, response


async def test_gate_precedes_settings_loading(monkeypatch, capsys):
    monkeypatch.delenv("RUN_LITEAPI_INTEGRATION_TESTS", raising=False)
    settings = Mock(side_effect=AssertionError("must not load settings"))
    monkeypatch.setattr(check_liteapi, "Settings", settings)
    assert await check_liteapi.run() == 1
    settings.assert_not_called()
    assert "FAIL LiteAPI gate" in capsys.readouterr().out


async def test_missing_key_never_constructs_http_client(monkeypatch, capsys):
    monkeypatch.setenv("RUN_LITEAPI_INTEGRATION_TESTS", "1")
    monkeypatch.setattr(check_liteapi, "Settings", lambda: Settings(_env_file=None))
    client = Mock(side_effect=AssertionError("must not construct HTTP client"))
    monkeypatch.setattr(check_liteapi.httpx, "AsyncClient", client)
    assert await check_liteapi.run() == 1
    client.assert_not_called()
    assert "liteapi_not_configured" in capsys.readouterr().out


@pytest.mark.parametrize("wrong_source", [False, True])
async def test_smoke_requires_valid_sandbox_domain_and_one_http(monkeypatch, capsys, wrong_source):
    monkeypatch.setenv("RUN_LITEAPI_INTEGRATION_TESTS", "1")
    monkeypatch.setattr(
        check_liteapi, "Settings", lambda: Settings(_env_file=None, liteapi_api_key=FAKE_KEY)
    )
    original_http = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return response()

    monkeypatch.setattr(
        check_liteapi.httpx,
        "AsyncClient",
        lambda **kwargs: original_http(**kwargs, transport=httpx.MockTransport(handler)),
    )
    original_map = check_liteapi.map_hotels

    def mapped(*args, **kwargs):
        hotels = original_map(*args, **kwargs)
        return (
            [h.model_copy(update={"data_source": TravelDataSource.DEMO}) for h in hotels]
            if wrong_source
            else hotels
        )

    monkeypatch.setattr(check_liteapi, "map_hotels", mapped)
    result = await check_liteapi.run()
    output = capsys.readouterr().out
    assert len(requests) == 1
    assert result == int(wrong_source)
    assert ("PASS Hotel domain/source: liteapi_sandbox" in output) is not wrong_source
    assert FAKE_KEY not in output
