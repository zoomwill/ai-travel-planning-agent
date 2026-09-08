"""No network, real credentials, sleeps, or response-body logging in unit tests."""

import asyncio
import io

import httpx
import pytest
from loguru import logger
from pydantic import SecretStr

from app.external.liteapi.client import LiteAPIClient
from app.external.liteapi.errors import LiteAPIError, LiteAPISchemaError
from app.external.liteapi.models import HotelRatesResponse
from app.external.liteapi.validation import validate_liteapi_response
from app.observability.logging import JsonLogSink
from tests.external.liteapi.helpers import FAKE_KEY, client, payload, response


async def test_auth_fixed_host_timeout_and_cleanup():
    def handler(request):
        assert request.headers["X-API-Key"] == FAKE_KEY
        assert request.url.host == "api.liteapi.travel"
        assert request.url.path == "/v3.0/hotels/rates"
        assert request.extensions["timeout"]["read"] == 20
        return response()

    api = client(handler)
    validate_liteapi_response(HotelRatesResponse, await api.hotel_rates({}))
    await api.aclose()
    assert api._http.is_closed
    bad = httpx.AsyncClient(base_url="https://evil.example")
    with pytest.raises(ValueError, match="fixed official host"):
        LiteAPIClient(bad, api_key=SecretStr(FAKE_KEY))
    await bad.aclose()


@pytest.mark.parametrize(
    "status,expected,calls",
    [
        (429, "liteapi_rate_limited", 2),
        (500, "liteapi_provider_error", 2),
        (502, "liteapi_provider_error", 2),
        (503, "liteapi_provider_error", 2),
        (504, "liteapi_provider_error", 2),
        (400, "liteapi_provider_error", 1),
        (401, "liteapi_authentication_failed", 1),
        (403, "liteapi_authentication_failed", 1),
        (302, "liteapi_provider_error", 1),
        (204, "liteapi_no_hotel_rates", 1),
    ],
)
async def test_bounded_retries_and_no_secret_errors(status, expected, calls):
    seen = []
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    def handler(request):
        seen.append(request)
        return response(
            {"error": FAKE_KEY}, status, {"Retry-After": "9999", "Location": "https://evil.example"}
        )

    api = client(handler, sleep=sleep)
    with pytest.raises(LiteAPIError) as error:
        await api.hotel_rates({})
    await api.aclose()
    assert error.value.code == expected
    assert FAKE_KEY not in str(error.value)
    assert len(seen) == calls
    assert sleeps == ([2.0] if calls == 2 else [])


@pytest.mark.parametrize(
    "failure,code",
    [(httpx.ReadTimeout, "liteapi_timeout"), (httpx.ConnectError, "liteapi_transport_error")],
)
async def test_transient_exception_retries(failure, code):
    seen = []

    async def sleep(_):
        pass

    def handler(request):
        seen.append(request)
        raise failure(FAKE_KEY)

    api = client(handler, sleep=sleep)
    with pytest.raises(LiteAPIError, match=code):
        await api.hotel_rates({})
    await api.aclose()
    assert len(seen) == 2


async def test_cancellation_propagates_and_never_retries():
    entered = asyncio.Event()
    count = 0

    async def handler(_):
        nonlocal count
        count += 1
        entered.set()
        await asyncio.Event().wait()

    api = client(handler)
    task = asyncio.create_task(api.hotel_rates({}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await api.aclose()
    assert count == 1


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null"])
async def test_invalid_json_is_safe(body):
    api = client(lambda _: httpx.Response(200, content=body))
    with pytest.raises(LiteAPIError, match="liteapi_invalid_response"):
        await api.hotel_rates({})
    await api.aclose()


def test_validation_reports_structure_only_and_tolerates_extras():
    good = payload()
    result = validate_liteapi_response(HotelRatesResponse, good)
    assert "offerId" not in result.model_dump_json()
    bad = payload()
    bad["data"][0]["roomTypes"][0]["rates"][0]["retailRate"]["total"][0]["amount"] = FAKE_KEY
    output = io.StringIO()
    handle = logger.add(JsonLogSink(output))
    try:
        with pytest.raises(LiteAPISchemaError) as error:
            validate_liteapi_response(HotelRatesResponse, bad)
    finally:
        logger.remove(handle)
    assert error.value.error_count == 1
    assert error.value.issues[0].loc.endswith("retailRate.total.0.amount")
    assert FAKE_KEY not in output.getvalue()
    assert "input" not in output.getvalue()
    assert "validation_error_type" in output.getvalue()


async def test_request_logs_do_not_contain_key_or_body():
    output = io.StringIO()
    handle = logger.add(JsonLogSink(output))
    api = client(lambda _: response({"secret": FAKE_KEY}, 401))
    try:
        with pytest.raises(LiteAPIError):
            await api.hotel_rates({"guestNationality": "US"})
    finally:
        await api.aclose()
        logger.remove(handle)
    assert FAKE_KEY not in output.getvalue()
    assert "guestNationality" not in output.getvalue()
    assert "X-API-Key" not in output.getvalue()
