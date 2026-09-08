"""Real hotel search is isolated from both ordinary and Docker integration suites."""

import os
import re

import pytest

from app.core.config import Settings
from scripts.check_liteapi import run


@pytest.mark.liteapi_integration
async def test_real_liteapi_sandbox_rates(capsys):
    """Use the same single-request, safe diagnostic smoke path."""
    if os.environ.get("RUN_LITEAPI_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_LITEAPI_INTEGRATION_TESTS=1 to allow real LiteAPI requests")
    if not Settings().liteapi_is_configured:
        pytest.skip("LiteAPI key is not configured")
    result = await run()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    safe = re.search(r"(?:sand_|sandbox_|prod_|sk-)[A-Za-z0-9_-]{16,}", output) is None
    if not safe:
        pytest.fail(
            "Smoke output failed credential-pattern safety check (values hidden)", pytrace=False
        )
    if result != 0:
        # The checker emits only bounded diagnostics; never expose pytest locals or provider data.
        with capsys.disabled():
            print(captured.out, end="")
        pytest.fail("Real LiteAPI sandbox smoke failed", pytrace=False)
    count = re.search(r"PASS Mapped hotel candidates: ([1-9][0-9]*)", output)
    if count is None or "PASS Hotel domain/source: liteapi_sandbox" not in output:
        pytest.fail("Real LiteAPI domain/source proof missing", pytrace=False)
    with capsys.disabled():
        print(captured.out, end="")
