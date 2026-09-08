"""Fixed-host, bounded, search-only LiteAPI HTTP transport."""

import asyncio
import json
import math
import time
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import SecretStr

from app.external.duffel.client import Sleep
from app.external.liteapi.errors import LiteAPIError
from app.observability.logging import log_event
from app.observability.metrics import MetricsRuntime
from app.search.models import JsonObject

LITEAPI_BASE_URL = "https://api.liteapi.travel"


class LiteAPIClient:
    """Own no per-search clients and expose only the hotel-rates operation."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_key: SecretStr,
        environment: Literal["sandbox", "production"] = "sandbox",
        timeout_seconds: float = 20,
        max_retries: int = 1,
        sleep: Sleep = asyncio.sleep,
        metrics: MetricsRuntime | None = None,
    ) -> None:
        if str(http_client.base_url).rstrip("/") != LITEAPI_BASE_URL:
            raise ValueError("LiteAPI client requires the fixed official host")
        if not 0 < timeout_seconds <= 60 or not 0 <= max_retries <= 2:
            raise ValueError("LiteAPI timeout or retry limit is invalid")
        self._http = http_client
        self._key = api_key
        self.environment = environment
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self.metrics = metrics

    async def hotel_rates(self, body: JsonObject) -> object:
        """Send one logical search, retrying only transient transport/status failures."""

        if not self._key.get_secret_value().strip():
            raise LiteAPIError("liteapi_not_configured")
        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            status = "error"
            response: httpx.Response | None = None
            try:
                response = await self._http.post(
                    LITEAPI_BASE_URL + "/v3.0/hotels/rates",
                    json=body,
                    headers={
                        "X-API-Key": self._key.get_secret_value(),
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                    follow_redirects=False,
                )
                if response.status_code == 204:
                    raise LiteAPIError("liteapi_no_hotel_rates")
                if response.status_code in {401, 403}:
                    raise LiteAPIError("liteapi_authentication_failed")
                if response.status_code == 429:
                    status = "rate_limited"
                    error = LiteAPIError("liteapi_rate_limited", recoverable=True)
                elif response.status_code in {500, 502, 503, 504}:
                    error = LiteAPIError("liteapi_provider_error", recoverable=True)
                elif response.status_code != 200:
                    raise LiteAPIError("liteapi_provider_error")
                else:
                    try:
                        # Parse money decimals directly, never through binary float arithmetic.
                        payload = json.loads(response.content, parse_float=Decimal)
                    except (ValueError, UnicodeError):
                        raise LiteAPIError("liteapi_invalid_response") from None
                    if not isinstance(payload, dict):
                        raise LiteAPIError("liteapi_invalid_response")
                    status = "success"
                    return payload
            except httpx.TimeoutException:
                status = "timeout"
                error = LiteAPIError("liteapi_timeout", recoverable=True)
            except httpx.TransportError:
                error = LiteAPIError("liteapi_transport_error", recoverable=True)
            finally:
                self._observe(status, time.monotonic() - started)
            if attempt == self._max_retries:
                raise error from None
            await self._sleep(self.retry_delay(response))
        raise LiteAPIError("liteapi_provider_error")

    @staticmethod
    def retry_delay(response: httpx.Response | None) -> float:
        """Accept a numeric Retry-After only, capped at two seconds."""

        try:
            value = float(response.headers.get("retry-after", "0.25")) if response else 0.1
        except ValueError:
            return 0.25
        return min(2.0, max(0.0, value)) if math.isfinite(value) else 0.25

    def _observe(self, status: str, duration: float) -> None:
        if self.metrics is not None:
            self.metrics.external_requests.labels(
                provider="liteapi", operation="hotel_rates", status=status
            ).inc()
            self.metrics.external_duration.labels(
                provider="liteapi", operation="hotel_rates", status=status
            ).observe(max(0, duration))
        log_event(
            "external_request_completed",
            "An external travel-data request completed.",
            provider="liteapi",
            operation="hotel_rates",
            environment=self.environment,
            status=status,
            duration_ms=round(max(0, duration) * 1000, 3),
        )

    async def aclose(self) -> None:
        """Close the lifespan-owned connection pool."""

        await self._http.aclose()
