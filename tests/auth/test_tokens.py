"""Actual local RS256 signatures, with no Auth0 network."""

import asyncio
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.tokens import AuthenticationError, TokenVerifier, user_reference


@pytest.mark.asyncio
async def test_valid_cache_concurrency_and_close(keys, auth_settings, token):
    calls = []

    def serve(request):
        calls.append(request.url)
        return httpx.Response(200, json={"keys": [keys[1]]})

    verifier = TokenVerifier(auth_settings, transport=httpx.MockTransport(serve))
    try:
        principals = await asyncio.gather(*[verifier.verify(token()) for _ in range(10)])
        assert len(calls) == 1
        assert str(calls[0]) == "https://tenant.example/.well-known/jwks.json"
        assert all(
            p.user_ref == user_reference(auth_settings.auth0_issuer, "auth0|user-a")
            for p in principals
        )
        assert "auth0|" not in repr(principals[0])
    finally:
        await verifier.aclose()
    assert verifier.client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"aud": "spa-client-id"},
        {"iss": "https://attacker.example/"},
        {"sub": ""},
        {"sub": None},
        {"exp": str(int(time.time()) + 1000)},
        {"nbf": int(time.time()) + 3600},
        {"iat": True},
    ],
)
async def test_invalid_claims(keys, auth_settings, token, change):
    verifier = TokenVerifier(
        auth_settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [keys[1]]})),
    )
    try:
        with pytest.raises(AuthenticationError):
            await verifier.verify(token(**change))
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant", ["malformed", "unsigned", "hs256", "no-kid", "no-sub", "wrong-signature"]
)
async def test_invalid_structure_signature_algorithm(keys, auth_settings, token, variant):
    claims = {
        "exp": int(time.time()) + 600,
        "iss": auth_settings.auth0_issuer,
        "aud": auth_settings.auth0_audience,
        "sub": "test",
    }
    if variant == "malformed":
        value = "not.a.token"
    elif variant == "unsigned":
        value = jwt.encode(claims, "", algorithm="none")
    elif variant == "hs256":
        value = jwt.encode(
            claims,
            "test-secret-that-is-only-for-local-unit-tests",
            algorithm="HS256",
            headers={"kid": "test-key"},
        )
    elif variant == "no-kid":
        value = jwt.encode(claims, keys[0], algorithm="RS256")
    else:
        if variant == "no-sub":
            del claims["sub"]
        key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            if variant == "wrong-signature"
            else keys[0]
        )
        value = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    verifier = TokenVerifier(
        auth_settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [keys[1]]})),
    )
    try:
        with pytest.raises(AuthenticationError):
            await verifier.verify(value)
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
async def test_unknown_kid_refresh_once_then_throttle(keys, auth_settings, token):
    calls = []

    def serve(_):
        calls.append(1)
        return httpx.Response(200, json={"keys": [keys[1]]})

    verifier = TokenVerifier(auth_settings, transport=httpx.MockTransport(serve))
    try:
        await verifier.verify(token())
        for kid in ("unknown-one", "unknown-two", "unknown-three"):
            value = jwt.encode({"sub": "test"}, keys[0], algorithm="RS256", headers={"kid": kid})
            with pytest.raises(AuthenticationError):
                await verifier.verify(value)
        assert len(calls) == 2
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
async def test_rotation_resolves_on_one_refresh(keys, auth_settings, token):
    jwk = dict(keys[1], kid="rotated-key")
    documents = iter([{"keys": [keys[1]]}, {"keys": [jwk]}])
    verifier = TokenVerifier(
        auth_settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(documents))),
    )
    try:
        await verifier.verify(token())
        claims = jwt.decode(token(), options={"verify_signature": False})
        rotated = jwt.encode(claims, keys[0], algorithm="RS256", headers={"kid": "rotated-key"})
        assert (await verifier.verify(rotated)).subject == "auth0|user-a"
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["timeout", "malformed", "empty", "oversized", "redirect"])
async def test_jwks_failures_are_safe_bounded(auth_settings, token, problem):
    calls = []

    def serve(request):
        calls.append(1)
        if problem == "timeout":
            raise httpx.ReadTimeout("private information", request=request)
        if problem == "redirect":
            return httpx.Response(302, headers={"Location": "https://attacker.example"})
        if problem == "empty":
            return httpx.Response(200, json={"keys": []})
        return httpx.Response(200, content="x" * (70000 if problem == "oversized" else 1))

    verifier = TokenVerifier(auth_settings, transport=httpx.MockTransport(serve))
    try:
        for _ in range(2):
            with pytest.raises(AuthenticationError, match="^jwks_unavailable$"):
                await verifier.verify(token())
        assert calls == [1]
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
async def test_expired_cache_refreshes(keys, auth_settings, token):
    calls = []

    def serve(_):
        calls.append(1)
        return httpx.Response(200, json={"keys": [keys[1]]})

    verifier = TokenVerifier(auth_settings, transport=httpx.MockTransport(serve))
    try:
        await verifier.verify(token())
        verifier._expires = 0
        await verifier.verify(token())
        assert len(calls) == 2
    finally:
        await verifier.aclose()


@pytest.mark.asyncio
async def test_total_deadline_and_cancellation(auth_settings, token):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def stalled(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    settings = auth_settings.model_copy(update={"auth_jwks_timeout_seconds": 0.02})
    verifier = TokenVerifier(settings, transport=httpx.MockTransport(stalled))
    try:
        with pytest.raises(AuthenticationError, match="^jwks_unavailable$"):
            await verifier.verify(token())
        assert cancelled.is_set()
    finally:
        await verifier.aclose()

    entered.clear()
    cancelled.clear()
    verifier = TokenVerifier(auth_settings, transport=httpx.MockTransport(stalled))
    try:
        task = asyncio.create_task(verifier.verify(token()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert not verifier._lock.locked()
        assert verifier._failed_refresh_at == float("-inf")
    finally:
        await verifier.aclose()
