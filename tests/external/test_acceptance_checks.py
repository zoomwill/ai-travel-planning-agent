"""Offline tests for assertions that guard the paid acceptance run."""

import httpx
import pytest

from tests.external.acceptance_checks import AcceptanceFailure, check_public_tree, check_state
from tests.external.liteapi.helpers import trip


@pytest.mark.parametrize(
    "value",
    [
        {"roomTypes": []},
        {"X-API-Key": "fake"},
        httpx.Response(200),
        RuntimeError("not public"),
        "sand_fake_credential_for_unit_test",
        "Bearer fake-value",
    ],
)
def test_public_boundary_rejects_internal_or_sensitive_data(value):
    with pytest.raises(AcceptanceFailure):
        check_public_tree(value)


def test_domain_and_bounded_checkpoint_values_are_allowed():
    check_state(
        {"requirements": trip(), "search_results": [{"kind": "flights", "data": [{}]}]}, 1, 1
    )
    with pytest.raises(AcceptanceFailure, match="candidate cap"):
        check_state({"search_results": [{"kind": "hotels", "data": [{}, {}]}]}, 1, 1)
