"""Pure ASGI request correlation and full-response HTTP metrics."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from loguru import logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.context import choose_request_id, reset_request_id, set_request_id
from app.observability.logging import log_event
from app.observability.metrics import HTTP_METHODS, MetricsRuntime, normalize_label

Clock = Callable[[], float]


class ObservabilityMiddleware:
    """Measure through the final response body without reading request bodies."""

    def __init__(
        self, app: ASGIApp, metrics: MetricsRuntime, clock: Clock = time.monotonic
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Correlate one HTTP request and always restore its async context."""

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id")
        supplied_request_id: str | None = None
        if supplied is not None:
            try:
                supplied_request_id = supplied.decode("ascii")
            except UnicodeDecodeError:
                pass
        request_id = choose_request_id(supplied_request_id)
        token = set_request_id(request_id)
        method = normalize_label(scope.get("method", "unknown"), HTTP_METHODS)
        path = str(scope.get("path", ""))
        excluded = path == "/metrics"
        started = self.clock()
        status_code = 500
        response_complete = False
        disconnected = False
        send_failed = False
        request_failed = False

        if not excluded:
            self.metrics.http_in_progress.labels(method=method).inc()

        async def receive_with_disconnect() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_complete, send_failed
            final_body = False
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers = [
                    (name, value)
                    for name, value in response_headers
                    if name.lower() != b"x-request-id"
                ]
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                final_body = True
            try:
                await send(message)
            except BaseException:
                send_failed = True
                raise
            if final_body:
                response_complete = True

        with logger.contextualize(request_id=request_id):
            try:
                await self.app(scope, receive_with_disconnect, send_with_request_id)
            except BaseException as exc:
                request_failed = True
                if disconnected or send_failed or isinstance(exc, asyncio.CancelledError):
                    status_code = 499
                raise
            finally:
                try:
                    duration = max(0.0, self.clock() - started)
                    route = _route_template(scope)
                    if disconnected and not response_complete:
                        status_code = 499
                    if not excluded:
                        normalized_status = _status_code(status_code)
                        self.metrics.http_in_progress.labels(method=method).dec()
                        self.metrics.http_requests.labels(
                            method=method,
                            route=route,
                            status_code=normalized_status,
                        ).inc()
                        self.metrics.http_duration.labels(method=method, route=route).observe(
                            duration
                        )
                        outcome = (
                            "disconnect"
                            if status_code == 499
                            else "error"
                            if request_failed
                            else "completed"
                        )
                        log_event(
                            "http_request_completed",
                            "HTTP response lifecycle completed.",
                            method=method,
                            route=route,
                            status_code=int(normalized_status),
                            duration_ms=round(duration * 1000, 3),
                            component="http",
                            outcome=outcome,
                        )
                finally:
                    reset_request_id(token)


def _route_template(scope: Scope) -> str:
    """Return the matched FastAPI path template, never a raw identifier."""

    route: Any = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path.startswith("/") else "unmatched"


def _status_code(value: int) -> str:
    """Bound the status label to the finite HTTP status-code range."""

    return str(value) if 100 <= value <= 599 else "500"
