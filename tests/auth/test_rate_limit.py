"""Pure quota-window and admission tests; actual Lua is tested separately with Docker."""

from unittest.mock import AsyncMock

import pytest

from app.auth.rate_limit import ADMIT_SCRIPT, admit, buckets
from app.core.config import Settings


def test_windows_expire_and_no_raw_identity():
    settings = Settings(_env_file=None)
    selected = buckets(settings, "a" * 64, "intake", 86399)
    assert len(selected) == 3
    assert all(item.ttl == 1 for item in selected)
    assert all("{travel-auth}" in item.key for item in selected)
    next_day = buckets(settings, "a" * 64, "intake", 86400)
    assert selected[1].key != next_day[1].key
    assert next_day[1].ttl == 86400
    assert len(buckets(settings, "a" * 64, "plan", 123)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["intake", "plan"])
@pytest.mark.parametrize("result", [0, 86400])
async def test_atomic_admission_result(operation, result):
    client = AsyncMock()
    client.eval.return_value = result
    assert await admit(client, Settings(_env_file=None), "a" * 64, operation) == result
    args = client.eval.call_args.args
    assert args[0] == ADMIT_SCRIPT
    assert args[1] == (3 if operation == "intake" else 2)
    assert "FLUSH" not in args[0]


@pytest.mark.asyncio
async def test_invalid_redis_result_fails_closed():
    client = AsyncMock()
    client.eval.return_value = None
    with pytest.raises(ValueError):
        await admit(client, Settings(_env_file=None), "a" * 64, "plan")
