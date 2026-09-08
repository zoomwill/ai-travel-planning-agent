"""FastAPI authentication guard plus explicit user/checkpoint scoping."""

from typing import Literal, cast

from fastapi import HTTPException, Request
from prometheus_client import CollectorRegistry, Counter

from app.auth.rate_limit import admit
from app.auth.tokens import AuthenticationError, CurrentPrincipal, TokenVerifier


class AuthMetrics:
    """Bound labels centrally; no identifiers, claims or JWT kid in metrics."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.events = Counter(
            "travel_planner_auth_events",
            "Authentication and quota outcomes.",
            ("operation", "outcome"),
            registry=registry,
        )

    def record(self, operation: str, outcome: str) -> None:
        """Collapse unknown inputs rather than allowing cardinality growth."""

        self.events.labels(
            operation
            if operation in {"authentication", "authorization", "intake", "plan"}
            else "unknown",
            outcome if outcome in {"success", "denied", "unavailable", "limited"} else "unknown",
        ).inc()


async def authorize_request(request: Request) -> None:
    """Authenticate and admit once, before any protected endpoint or SSE preparation."""

    settings = request.app.state.settings
    if settings.auth_mode == "demo":
        return
    metrics: AuthMetrics = request.app.state.auth_metrics
    verifier: TokenVerifier = request.app.state.token_verifier
    headers = request.headers.getlist("authorization")
    try:
        if len(headers) != 1:
            raise AuthenticationError()
        parts = headers[0].split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise AuthenticationError()
        principal = await verifier.verify(parts[1])
    except AuthenticationError as error:
        unavailable = error.code == "jwks_unavailable"
        metrics.record("authentication", "unavailable" if unavailable else "denied")
        raise HTTPException(
            503 if unavailable else 401,
            detail={
                "code": "authentication_unavailable" if unavailable else "authentication_required",
                "message": "Authentication is unavailable." if unavailable else "Sign in again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    request.state.principal = principal
    metrics.record("authentication", "success")
    # Router dependencies run once, including the streaming preparation dependency.
    operation: Literal["intake", "plan"] | None = None
    if request.method == "POST":
        operation = "intake" if request.url.path.endswith("/messages") else "plan"
        if request.url.path.endswith("/reset"):
            operation = None
    if operation is not None:
        try:
            retry_after = await admit(
                request.app.state.resources.redis_client, settings, principal.user_ref, operation
            )
        except Exception:
            metrics.record(operation, "unavailable")
            raise HTTPException(
                503,
                detail={
                    "code": "rate_limit_unavailable",
                    "message": "Planning capacity is unavailable.",
                },
            ) from None
        if retry_after:
            metrics.record(operation, "limited")
            raise HTTPException(
                429,
                detail={
                    "code": "capacity_reached",
                    "message": "Daily demo capacity reached. Please try again later.",
                },
                headers={"Retry-After": str(retry_after)},
            )
        metrics.record(operation, "success")


def request_user_id(request: Request, legacy: str | None) -> str:
    """Ignore every client-supplied identity in auth0 mode, including legacy paths."""

    if request.app.state.settings.auth_mode == "auth0":
        principal = cast(CurrentPrincipal, request.state.principal)
        return principal.user_ref
    from app.api.routes.persistence import _validate_user_id

    return _validate_user_id(legacy or "")


def checkpoint_thread_id(request: Request, public_id: str) -> str:
    """Namespace checkpoint keys without changing public IDs or demo compatibility."""

    if request.app.state.settings.auth_mode == "auth0":
        return f"auth0:{request_user_id(request, None)}:{public_id}"
    return public_id


def record_resource_denied(request: Request) -> None:
    """Count missing scoped resources without probing whether another owner has them."""

    if request.app.state.settings.auth_mode == "auth0":
        metrics: AuthMetrics = request.app.state.auth_metrics
        metrics.record("authorization", "denied")
