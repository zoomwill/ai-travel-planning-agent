"""Strict JSON-safe models crossing the local MCP protocol boundary."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.models import TripRequirements


class MCPModel(BaseModel):
    """Reject unknown protocol fields and validate default values."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)


class MCPTripRequirements(MCPModel):
    """A JSON-only representation of the existing travel requirements."""

    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    start_date: str = Field(min_length=1)
    end_date: str = Field(min_length=1)
    budget: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    travelers: int = Field(gt=0)
    preferences: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, requirements: TripRequirements) -> Self:
        """Serialize date, Decimal, and Enum fields through Pydantic JSON mode."""

        return cls.model_validate(requirements.model_dump(mode="json"))

    def to_domain(self) -> TripRequirements:
        """Delegate all business validation to the existing domain model."""

        return TripRequirements.model_validate(self.model_dump(mode="json"))


class MCPToolRequest(MCPModel):
    """One traceable, deterministic request sent to an MCP travel tool."""

    task_id: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(min_length=1, max_length=128)
    requirements: MCPTripRequirements
    route_origin: str | None = Field(default=None, min_length=1)
    route_destination: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_route_pair(self) -> Self:
        """Require both optional route endpoints together or neither one."""

        if (self.route_origin is None) != (self.route_destination is None):
            raise ValueError("route_origin and route_destination must be provided together")
        return self


class MCPToolError(MCPModel):
    """A deliberately small error safe to cross process boundaries."""

    error_type: str = Field(min_length=1, max_length=64)
    safe_message: str = Field(min_length=1, max_length=256)
    recoverable: bool


class MCPToolResponse(MCPModel):
    """The single success-or-error envelope returned by all five tools."""

    ok: bool
    tool_name: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(min_length=1, max_length=128)
    data: JsonValue = None
    error: MCPToolError | None = None
    provider: str = Field(default="deterministic_mock", pattern=r"^deterministic_mock$")

    @model_validator(mode="after")
    def validate_success_or_error(self) -> Self:
        """Prevent ambiguous envelopes containing both data and an error."""

        if self.ok and (self.error is not None or self.data is None):
            raise ValueError("a successful MCP response needs data and no error")
        if not self.ok and (self.data is not None or self.error is None):
            raise ValueError("a failed MCP response needs an error and no data")
        return self


def successful_response(
    request: MCPToolRequest,
    tool_name: str,
    data: JsonValue,
) -> MCPToolResponse:
    """Build a validated successful envelope without duplicating metadata."""

    return MCPToolResponse(
        ok=True,
        tool_name=tool_name,
        task_id=request.task_id,
        request_fingerprint=request.request_fingerprint,
        data=data,
    )


def failed_response(
    request: MCPToolRequest,
    tool_name: str,
    *,
    error_type: str = "provider_error",
) -> MCPToolResponse:
    """Build a sanitized failure envelope without exception text or traceback."""

    return MCPToolResponse(
        ok=False,
        tool_name=tool_name,
        task_id=request.task_id,
        request_fingerprint=request.request_fingerprint,
        error=MCPToolError(
            error_type=error_type,
            safe_message=f"The {tool_name} tool could not complete the request.",
            recoverable=False,
        ),
    )
