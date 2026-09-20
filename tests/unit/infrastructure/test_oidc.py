from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK

from core_platform.foundation.errors import AuthenticationError
from core_platform.infrastructure.security.oidc import (
    OidcConfiguration,
    OidcJwksCache,
    OidcTokenAuthenticator,
)

ISSUER = "https://issuer.example"
AUDIENCE = "core-data-api"
KID = "key-1"


class FakeJwksCache:
    def __init__(self, key: PyJWK | None) -> None:
        self.key = key
        self.calls = 0

    async def get(self, kid: str) -> PyJWK:
        self.calls += 1
        if self.key is None or kid != KID:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Unknown signing key")
        return self.key


def _keys() -> tuple[Any, PyJWK]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = KID
    public_jwk["alg"] = "RS256"
    return private_key, PyJWK.from_dict(public_jwk)


def _token(private_key: Any, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "scope": "openid profile",
        "azp": "core-data-cli",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


def _authenticator(cache: FakeJwksCache) -> OidcTokenAuthenticator:
    return OidcTokenAuthenticator(
        OidcConfiguration(
            issuer=ISSUER,
            audience=AUDIENCE,
            allowed_algorithms=("RS256",),
            jwks_ttl_seconds=300,
            clock_skew_seconds=30,
        ),
        jwks_cache=cache,
    )


def test_valid_rs256_token_is_accepted() -> None:
    private_key, public_key = _keys()
    authenticator = _authenticator(FakeJwksCache(public_key))
    context = asyncio.run(authenticator.authenticate(_token(private_key)))
    assert context.issuer == ISSUER
    assert context.subject == "subject-1"
    assert context.audience == (AUDIENCE,)
    assert context.scopes == frozenset({"openid", "profile"})


def test_wrong_audience_is_rejected() -> None:
    private_key, public_key = _keys()
    authenticator = _authenticator(FakeJwksCache(public_key))
    token = _token(private_key, aud="other-api")
    with pytest.raises(AuthenticationError) as caught:
        asyncio.run(authenticator.authenticate(token))
    assert caught.value.code == "AUTH.TOKEN.INVALID"


def test_expired_token_is_rejected() -> None:
    private_key, public_key = _keys()
    now = datetime.now(UTC)
    authenticator = _authenticator(FakeJwksCache(public_key))
    token = _token(private_key, exp=int((now - timedelta(minutes=5)).timestamp()))
    with pytest.raises(AuthenticationError):
        asyncio.run(authenticator.authenticate(token))


def test_algorithm_is_checked_before_jwks_lookup() -> None:
    cache = FakeJwksCache(None)
    authenticator = _authenticator(cache)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": AUDIENCE,
            "iat": 1,
            "exp": 4_000_000_000,
        },
        "not-a-production-secret-but-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": KID},
    )
    with pytest.raises(AuthenticationError):
        asyncio.run(authenticator.authenticate(token))
    assert cache.calls == 0


def test_unknown_kid_fails_closed() -> None:
    private_key, _ = _keys()
    cache = FakeJwksCache(None)
    authenticator = _authenticator(cache)
    with pytest.raises(AuthenticationError):
        asyncio.run(authenticator.authenticate(_token(private_key)))
    assert cache.calls == 1


def test_jwks_cache_refreshes_once_for_unknown_kid() -> None:
    private_key, _ = _keys()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = KID
    jwk["alg"] = "RS256"
    calls = {"discovery": 0, "jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            calls["discovery"] += 1
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.path == "/jwks":
            calls["jwks"] += 1
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = OidcJwksCache(
                OidcConfiguration(
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    allowed_algorithms=("RS256",),
                    jwks_ttl_seconds=300,
                    clock_skew_seconds=30,
                ),
                client,
            )
            with pytest.raises(AuthenticationError):
                await cache.get("unknown-kid")

    asyncio.run(run())
    assert calls == {"discovery": 1, "jwks": 1}


def test_jwks_cache_ignores_encryption_keys() -> None:
    signing_private_key, _ = _keys()
    signing_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        signing_private_key.public_key(),
        as_dict=True,
    )
    signing_jwk["kid"] = KID
    signing_jwk["alg"] = "RS256"
    signing_jwk["use"] = "sig"

    encryption_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    encryption_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        encryption_private_key.public_key(),
        as_dict=True,
    )
    encryption_jwk["kid"] = "encryption-key"
    encryption_jwk["alg"] = "RSA-OAEP"
    encryption_jwk["use"] = "enc"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.path == "/jwks":
            return httpx.Response(
                200,
                json={"keys": [encryption_jwk, signing_jwk]},
            )
        return httpx.Response(404)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = OidcJwksCache(
                OidcConfiguration(
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    allowed_algorithms=("RS256",),
                    jwks_ttl_seconds=300,
                    clock_skew_seconds=30,
                ),
                client,
            )

            key = await cache.get(KID)

            assert key.key_id == KID
            assert key.algorithm_name == "RS256"

    asyncio.run(run())


def test_jwks_cache_coalesces_concurrent_refreshes() -> None:
    private_key, _ = _keys()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = KID
    jwk["alg"] = "RS256"
    calls = {"discovery": 0, "jwks": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            calls["discovery"] += 1
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.path == "/jwks":
            calls["jwks"] += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = OidcJwksCache(
                OidcConfiguration(
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    allowed_algorithms=("RS256",),
                    jwks_ttl_seconds=300,
                    clock_skew_seconds=30,
                ),
                client,
            )
            keys = await asyncio.gather(*(cache.get(KID) for _ in range(20)))
            assert all(key.key_id == KID for key in keys)

    asyncio.run(run())
    assert calls == {"discovery": 1, "jwks": 1}


def test_jwks_cache_coalesces_concurrent_unknown_kid_refreshes() -> None:
    private_key, _ = _keys()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = KID
    jwk["alg"] = "RS256"
    calls = {"discovery": 0, "jwks": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            calls["discovery"] += 1
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.path == "/jwks":
            calls["jwks"] += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    async def get_unknown(cache: OidcJwksCache) -> None:
        with pytest.raises(AuthenticationError):
            await cache.get("unknown-kid")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = OidcJwksCache(
                OidcConfiguration(
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    allowed_algorithms=("RS256",),
                    jwks_ttl_seconds=300,
                    clock_skew_seconds=30,
                ),
                client,
            )
            await asyncio.gather(*(get_unknown(cache) for _ in range(20)))

    asyncio.run(run())
    assert calls == {"discovery": 1, "jwks": 1}


def test_wrong_issuer_is_rejected() -> None:
    private_key, public_key = _keys()
    authenticator = _authenticator(FakeJwksCache(public_key))
    token = _token(private_key, iss="https://other-issuer.example")
    with pytest.raises(AuthenticationError):
        asyncio.run(authenticator.authenticate(token))


def test_invalid_signature_is_rejected() -> None:
    _, trusted_public_key = _keys()
    attacker_private_key, _ = _keys()
    authenticator = _authenticator(FakeJwksCache(trusted_public_key))
    with pytest.raises(AuthenticationError):
        asyncio.run(authenticator.authenticate(_token(attacker_private_key)))


def test_jwks_outage_fails_closed_when_no_valid_cached_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cache = OidcJwksCache(
                OidcConfiguration(
                    issuer=ISSUER,
                    audience=AUDIENCE,
                    allowed_algorithms=("RS256",),
                    jwks_ttl_seconds=300,
                    clock_skew_seconds=30,
                ),
                client,
            )
            with pytest.raises(AuthenticationError):
                await cache.get(KID)

    asyncio.run(run())
