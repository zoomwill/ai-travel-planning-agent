"""Redis fixed-window admission: atomically check every cap, then consume all buckets."""

import time
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis

from app.core.config import Settings

# One EVAL owns check + increment + expiry for all keys. Redis failure never grants admission.
ADMIT_SCRIPT = """
local wait = 0
for i, key in ipairs(KEYS) do
    local limit = tonumber(ARGV[(i - 1) * 2 + 1])
    local ttl = tonumber(ARGV[(i - 1) * 2 + 2])
    if tonumber(redis.call('GET', key) or '0') >= limit then
        wait = math.max(wait, ttl)
    end
end
if wait > 0 then return wait end
for i, key in ipairs(KEYS) do
    redis.call('INCR', key)
    redis.call('EXPIRE', key, tonumber(ARGV[(i - 1) * 2 + 2]))
end
return 0
"""


@dataclass(frozen=True)
class Bucket:
    """A pseudonymous key, maximum count, and seconds until its UTC boundary."""

    key: str
    limit: int
    ttl: int


def buckets(
    settings: Settings, user_ref: str, operation: Literal["intake", "plan"], now: int
) -> list[Bucket]:
    """Build isolated rate keys without raw identity or travel data."""

    day, minute = now // 86400, now // 60
    day_ttl, minute_ttl = 86400 - now % 86400, 60 - now % 60
    if operation == "intake":
        return [
            Bucket(
                f"rate:{{travel-auth}}:intake:m:{user_ref}:{minute}",
                settings.auth_rate_intake_per_minute,
                minute_ttl,
            ),
            Bucket(
                f"rate:{{travel-auth}}:intake:d:{user_ref}:{day}",
                settings.auth_rate_intake_per_day,
                day_ttl,
            ),
            Bucket(
                f"rate:{{travel-auth}}:global-intake:{day}",
                settings.auth_rate_global_intake_per_day,
                day_ttl,
            ),
        ]
    return [
        Bucket(
            f"rate:{{travel-auth}}:plan:{user_ref}:{day}", settings.auth_rate_plan_per_day, day_ttl
        ),
        Bucket(
            f"rate:{{travel-auth}}:global-plan:{day}",
            settings.auth_rate_global_plan_per_day,
            day_ttl,
        ),
    ]


async def admit(
    client: Redis, settings: Settings, user_ref: str, operation: Literal["intake", "plan"]
) -> int:
    """Return zero on admission or safe Retry-After seconds; propagate Redis failure."""

    selected = buckets(settings, user_ref, operation, int(time.time()))
    args = [number for bucket in selected for number in (bucket.limit, bucket.ttl)]
    result = await client.eval(
        ADMIT_SCRIPT, len(selected), *[bucket.key for bucket in selected], *args
    )
    if type(result) is not int or not 0 <= result <= 86400:
        raise ValueError("invalid rate-limit result")
    return result
