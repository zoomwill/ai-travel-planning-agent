"""Safe Duffel schema validation diagnostics never expose provider values."""

import json
from io import StringIO

import pytest
from pydantic import ValidationError

from app.external.duffel.errors import DuffelSchemaError
from app.external.duffel.models import OfferRequestResponse
from app.external.duffel.validation import validate_duffel_response
from app.observability.logging import configure_logging, shutdown_logging
from tests.external.duffel.helpers import offer


@pytest.mark.asyncio
async def test_schema_diagnostics_include_only_count_location_and_type() -> None:
    private_marker = "Bearer unit-secret-must-not-appear"
    value = offer()
    value["authorization"] = private_marker
    segment = value["slices"][0]["segments"][0]
    segment["operating_carrier_flight_number"] = 4321
    segment["marketing_carrier"] = private_marker

    output = StringIO()
    lease = configure_logging("INFO", target=output)
    try:
        with pytest.raises(DuffelSchemaError) as captured:
            validate_duffel_response(
                OfferRequestResponse,
                {"data": {"offers": [value]}},
                operation="flight_offer_request",
            )
    finally:
        await shutdown_logging(lease)

    error = captured.value
    assert error.error_count == 2
    assert {(issue.loc, issue.type) for issue in error.issues} == {
        (
            "data.offers.0.slices.0.segments.0.operating_carrier_flight_number",
            "string_type",
        ),
        ("data.offers.0.slices.0.segments.0.marketing_carrier", "model_type"),
    }
    assert str(error) == "duffel_invalid_response"

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) == 2
    assert all(record["provider"] == "duffel" for record in records)
    assert all(record["operation"] == "flight_offer_request" for record in records)
    assert all(record["validation_error_count"] == 2 for record in records)
    assert {record["validation_error_loc"] for record in records} == {
        issue.loc for issue in error.issues
    }
    assert {record["validation_error_type"] for record in records} == {
        issue.type for issue in error.issues
    }
    serialized = output.getvalue()
    assert private_marker not in serialized
    assert "unit-secret-must-not-appear" not in serialized
    assert "authorization" not in serialized


@pytest.mark.parametrize(
    ("mutation", "expected_loc"),
    [
        ("numeric_duration", ("data", "offers", 0, "slices", 0, "duration")),
        ("missing_offers", ("data", "offers")),
    ],
)
def test_consumed_envelope_and_duration_types_remain_strict(
    mutation: str,
    expected_loc: tuple[str | int, ...],
) -> None:
    payload: dict[str, object] = {"data": {"offers": [offer()]}}
    if mutation == "numeric_duration":
        data = payload["data"]
        assert isinstance(data, dict)
        offers = data["offers"]
        assert isinstance(offers, list)
        offers[0]["slices"][0]["duration"] = 3600
    else:
        payload = {"data": {}}

    with pytest.raises(ValidationError) as captured:
        OfferRequestResponse.model_validate(payload)

    assert captured.value.errors(include_input=False)[0]["loc"] == expected_loc
