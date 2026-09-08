"""RS256 access-token verification with an async, bounded, application-owned JWKS cache."""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field

import httpx
import jwt

from app.core.config import Settings


class AuthenticationError(Exception):
    """A bounded category only: never include a JWT, claims, or provider response."""

    def __init__(self, code: str = "invalid_token") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    """Verified minimal identity; raw subject is never represented or persisted."""

    subject: str = field(repr=False)
    user_ref: str


def user_reference(issuer: str, subject: str) -> str:
    """Pseudonymize issuer/subject deterministically; this is not encryption."""

    return hashlib.sha256(f"travel-planner:user:v1\0{issuer}\0{subject}".encode()).hexdigest()


class TokenVerifier:
    """Own a single async pool and key cache; never fetch URLs from token headers."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.auth_jwks_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._forced_refresh_at = float("-inf")
        self._failed_refresh_at = float("-inf")
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close the owned network pool during application shutdown."""

        await self.client.aclose()

    async def _download(self) -> bytes:
        async with self.client.stream(
            "GET", self.settings.auth0_issuer + ".well-known/jwks.json"
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("bounded JWKS exceeded")
            return bytes(body)

    async def _refresh(self) -> None:
        try:
            body = await asyncio.wait_for(
                self._download(), timeout=self.settings.auth_jwks_timeout_seconds
            )
            import json

            document = json.loads(body)
            values = document["keys"]
            if not isinstance(values, list) or not 1 <= len(values) <= 32:
                raise ValueError("invalid key count")
            keys: dict[str, jwt.PyJWK] = {}
            for item in values:
                if item.get("kty") != "RSA" or item.get("use", "sig") != "sig":
                    continue
                if item.get("alg", "RS256") != "RS256":
                    continue
                kid = item.get("kid")
                if not isinstance(kid, str) or not 1 <= len(kid) <= 128 or kid in keys:
                    raise ValueError("invalid key identifier")
                if "d" in item or len(item.get("n", "")) > 1500:
                    raise ValueError("invalid public key")
                key = jwt.PyJWK.from_dict(item, algorithm="RS256")
                if not 2048 <= key.key.key_size <= 8192:
                    raise ValueError("invalid RSA size")
                keys[kid] = key
            if not keys:
                raise ValueError("no signing keys")
            self._keys = keys
            self._expires = time.monotonic() + self.settings.auth_jwks_cache_ttl_seconds
        except Exception:
            self._failed_refresh_at = time.monotonic()
            raise AuthenticationError("jwks_unavailable") from None

    async def _key(self, kid: str) -> jwt.PyJWK:
        async with self._lock:
            now = time.monotonic()
            expired = now >= self._expires
            if expired or kid not in self._keys:
                if now - self._failed_refresh_at < 30:
                    raise AuthenticationError("jwks_unavailable")
                if expired:
                    await self._refresh()
                elif now - self._forced_refresh_at >= 30:
                    # One forced refresh for rotation; bound random-kid request amplification.
                    self._forced_refresh_at = now
                    await self._refresh()
            key = self._keys.get(kid)
            if key is None:
                raise AuthenticationError()
            return key

    async def verify(self, token: str) -> CurrentPrincipal:
        """Require fixed RS256, exact issuer/API audience, expiry and a bounded subject."""

        try:
            if not 1 <= len(token) <= 16384:
                raise AuthenticationError()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 128:
                raise AuthenticationError()
            if header.get("crit") or header.get("b64") is False:
                raise AuthenticationError()
            key = await self._key(kid)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.settings.auth0_issuer,
                audience=self.settings.auth0_audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
                raise AuthenticationError()
            if any(ord(char) < 32 for char in subject):
                raise AuthenticationError()
            for name in ("exp", "nbf", "iat"):
                if name in claims and type(claims[name]) not in (int, float):
                    raise AuthenticationError()
            return CurrentPrincipal(subject, user_reference(self.settings.auth0_issuer, subject))
        except AuthenticationError:
            raise
        except Exception:
            raise AuthenticationError() from None
