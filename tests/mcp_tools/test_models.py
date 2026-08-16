"""Tests for strict JSON-safe MCP protocol models."""

import json

import pytest
from pydantic import ValidationError

from app.mcp_tools.models import MCPToolError, MCPToolResponse, MCPTripRequirements
from tests.mcp_tools.helpers import requirements


def test_domain_round_trip_is_json_safe() -> None:
    domain = requirements()
    protocol = MCPTripRequirements.from_domain(domain)

    encoded = json.dumps(protocol.model_dump(mode="json"))

    assert '"2027-04-10"' in encoded
    assert '"12000.00"' in encoded
    assert '"CNY"' in encoded
    assert protocol.to_domain() == domain


def test_domain_validation_is_reused_on_return() -> None:
    protocol = MCPTripRequirements.from_domain(requirements()).model_copy(
        update={"end_date": "2027-04-01"}
    )

    with pytest.raises(ValidationError, match="end_date"):
        protocol.to_domain()


def test_response_requires_exactly_one_success_or_error_shape() -> None:
    with pytest.raises(ValidationError):
        MCPToolResponse(
            ok=True,
            tool_name="get_weather",
            task_id="task",
            request_fingerprint="fingerprint",
            data=None,
        )

    error = MCPToolError(
        error_type="provider_error", safe_message="Unavailable.", recoverable=False
    )
    failed = MCPToolResponse(
        ok=False,
        tool_name="get_weather",
        task_id="task",
        request_fingerprint="fingerprint",
        error=error,
    )
    assert failed.data is None
    assert "traceback" not in failed.model_dump_json().casefold()
