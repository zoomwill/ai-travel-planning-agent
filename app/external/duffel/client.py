"""Bounded async HTTP client for Duffel's fixed official API host."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeAlias

import httpx
from pydantic import SecretStr

from app.external.duffel.errors import DuffelError, DuffelErrorCode
from app.observability.logging import log_event
from app.observability.metrics import MetricsRuntime

DUFFEL_API_BASE_URL = "https://api.duffel.com"
DuffelOperation: TypeAlias = Literal[
    "flight_offer_request", "stay_search", "stay_rates", "location_lookup"
]
Sleep = Callable[[float], Awaitable[None]]
_RETRYABLE_STATUS_CODES = frozenset({429, 503, 504})


class DuffelClient:
    """Send authenticated requests with a fixed host, timeout, and retry ceiling."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        access_token: SecretStr,
        environment: Literal["test", "live"],
        api_version: Literal["v2"],
        timeout_seconds: float,
        max_retries: int,
        sleep: Sleep = asyncio.sleep,
        metrics: MetricsRuntime | None = None,
    ) -> None:
        if str(http_client.base_url).rstrip("/") != DUFFEL_API_BASE_URL:
            raise ValueError("Duffel HTTP client must use the fixed official API host")
        self._http = http_client
        self._token = access_token
        self.environment = environment
        self._api_version = api_version
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self.metrics = metrics

    async def get(self, path: str, *, params: dict[str, str], operation: DuffelOperation) -> Any:
        """Send one GET and return only decoded JSON."""

        return await self._request("GET", path, operation=operation, params=params)

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        operation: DuffelOperation,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Send one POST and return only decoded JSON."""

        return await self._request(
            "POST",
            path,
            operation=operation,
            params=params,
            json=json,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: DuffelOperation,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if not self._token.get_secret_value():
            raise DuffelError("duffel_not_configured")
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Duffel request path must be relative to the fixed API host")

        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            status = "error"
            result_count: int | None = None
            response: httpx.Response | None = None
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {self._token.get_secret_value()}",
                        "Duffel-Version": self._api_version,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
                if response.status_code == 429:
                    status = "rate_limited"
                    error = DuffelError("duffel_rate_limited", recoverable=True)
                elif response.status_code == 401:
                    raise DuffelError("duffel_authentication_failed")
                elif response.status_code == 403:
                    code: DuffelErrorCode = (
                        "duffel_stays_access_denied"
                        if operation in {"stay_search", "stay_rates"}
                        else "duffel_authentication_failed"
                    )
                    status = "access_denied"
                    raise DuffelError(code)
                elif response.status_code in {503, 504}:
                    error = DuffelError("duffel_provider_error", recoverable=True)
                elif response.is_error:
                    raise DuffelError("duffel_provider_error")
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise DuffelError("duffel_invalid_response") from exc
                    if not isinstance(payload, dict):
                        raise DuffelError("duffel_invalid_response")
                    status = "success"
                    result_count = self._safe_result_count(operation, payload)
                    return payload
            except httpx.TimeoutException as exc:
                status = "timeout"
                error = DuffelError("duffel_timeout", recoverable=True)
                if attempt >= self._max_retries:
                    raise error from exc
            except httpx.TransportError as exc:
                error = DuffelError("duffel_transport_error", recoverable=True)
                if attempt >= self._max_retries:
                    raise error from exc
            finally:
                self._observe(
                    operation,
                    status,
                    time.monotonic() - started,
                    result_count=result_count,
                )

            if attempt >= self._max_retries:
                raise error
            await self._sleep(self._retry_delay(response))

        raise DuffelError("duffel_provider_error")

    @staticmethod
    def _retry_delay(response: httpx.Response | None) -> float:
        """Use Duffel's bounded rate-limit reset hint without long sleeps."""

        if response is None or response.status_code not in _RETRYABLE_STATUS_CODES:
            return 0.1
        raw = response.headers.get("ratelimit-reset")
        if raw is None:
            return 0.25
        try:
            value = float(raw)
        except ValueError:
            return 0.25
        delay = value - time.time() if value > 10_000 else value
        return min(2.0, max(0.0, delay))

    @staticmethod
    def _safe_result_count(operation: DuffelOperation, payload: dict[str, Any]) -> int:
        """Count only the bounded result collection for a known operation."""

        data = payload.get("data")
        if operation == "location_lookup":
            return len(data) if isinstance(data, list) else 0
        if not isinstance(data, dict):
            return 0
        collection_name = {
            "flight_offer_request": "offers",
            "stay_search": "results",
            "stay_rates": "rates",
        }.get(operation)
        collection = data.get(collection_name) if collection_name is not None else None
        return len(collection) if isinstance(collection, list) else 0

    def _observe(
        self,
        operation: DuffelOperation,
        status: str,
        duration: float,
        *,
        result_count: int | None,
    ) -> None:
        """Record bounded labels and a body-free structured log."""

        if self.metrics is not None:
            self.metrics.external_requests.labels(
                provider="duffel", operation=operation, status=status
            ).inc()
            self.metrics.external_duration.labels(
                provider="duffel", operation=operation, status=status
            ).observe(max(0.0, duration))
        log_event(
            "external_request_completed",
            "An external travel-data request completed.",
            component="external",
            provider="duffel",
            operation=operation,
            environment=self.environment,
            status=status,
            duration_ms=round(max(0.0, duration) * 1000, 3),
            result_count=result_count or 0,
        )

    async def aclose(self) -> None:
        """Close the one shared application-owned HTTP client."""

        await self._http.aclose()
