from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWK

from core_platform.foundation.errors import AuthenticationError
from core_platform.platform_kernel.identity import AuthenticationContext


@dataclass(frozen=True, slots=True)
class OidcConfiguration:
    issuer: str
    audience: str
    allowed_algorithms: tuple[str, ...]
    jwks_ttl_seconds: int
    clock_skew_seconds: int


class SigningKeyCache(Protocol):
    async def get(self, kid: str) -> PyJWK: ...


class OidcJwksCache:
    def __init__(
        self,
        configuration: OidcConfiguration,
        client: httpx.AsyncClient,
    ) -> None:
        self._configuration = configuration
        self._client = client
        self._keys: dict[str, PyJWK] = {}
        self._expires_at = 0.0
        self._jwks_uri: str | None = None
        self._generation = 0
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> PyJWK:
        now = monotonic()
        key = self._keys.get(kid)
        if key is not None and now < self._expires_at:
            return key
        observed_generation = self._generation
        async with self._lock:
            now = monotonic()
            key = self._keys.get(kid)
            if key is not None and now < self._expires_at:
                return key
            if self._generation != observed_generation and now < self._expires_at:
                raise AuthenticationError("AUTH.TOKEN.INVALID", "Unknown signing key")
            await self._refresh()
            self._generation += 1
            key = self._keys.get(kid)
            if key is None:
                raise AuthenticationError("AUTH.TOKEN.INVALID", "Unknown signing key")
            return key

    async def _refresh(self) -> None:
        try:
            if self._jwks_uri is None:
                discovery_url = (
                    f"{self._configuration.issuer.rstrip('/')}/.well-known/openid-configuration"
                )
                discovery_response = await self._client.get(discovery_url)
                discovery_response.raise_for_status()
                discovery = discovery_response.json()
                if discovery.get("issuer") != self._configuration.issuer.rstrip("/"):
                    raise AuthenticationError("AUTH.TOKEN.INVALID", "OIDC issuer mismatch")
                jwks_uri = discovery.get("jwks_uri")
                if not isinstance(jwks_uri, str) or not jwks_uri:
                    raise AuthenticationError("AUTH.TOKEN.INVALID", "OIDC JWKS URI missing")
                self._jwks_uri = jwks_uri

            jwks_uri = self._jwks_uri
            if jwks_uri is None:
                raise AuthenticationError("AUTH.TOKEN.INVALID", "OIDC JWKS URI missing")
            response = await self._client.get(jwks_uri)
            response.raise_for_status()
            payload = response.json()
            keys = payload.get("keys")
            if not isinstance(keys, list):
                raise AuthenticationError("AUTH.TOKEN.INVALID", "Invalid JWKS response")
            parsed: dict[str, PyJWK] = {}
            for raw_key in keys:
                if not isinstance(raw_key, dict):
                    continue

                # OIDC JWKS endpoints may expose encryption keys in addition to
                # signing keys. P0-I2 accepts only verification keys compatible
                # with the explicit JWT algorithm allowlist.
                key_use = raw_key.get("use")
                if key_use is not None and key_use != "sig":
                    continue

                declared_algorithm = raw_key.get("alg")
                if (
                    declared_algorithm is not None
                    and declared_algorithm not in self._configuration.allowed_algorithms
                ):
                    continue

                kid = raw_key.get("kid")
                if not isinstance(kid, str) or not kid:
                    continue

                key = PyJWK.from_dict(raw_key)
                if key.algorithm_name not in self._configuration.allowed_algorithms:
                    continue

                if kid in parsed:
                    raise AuthenticationError(
                        "AUTH.TOKEN.INVALID",
                        "Duplicate JWKS key identifier",
                    )
                parsed[kid] = key
            if not parsed:
                raise AuthenticationError(
                    "AUTH.TOKEN.INVALID",
                    "No usable JWKS signing keys",
                )
            self._keys = parsed
            self._expires_at = monotonic() + self._configuration.jwks_ttl_seconds
        except AuthenticationError:
            raise
        except (httpx.HTTPError, jwt.PyJWTError, ValueError, TypeError) as exc:
            raise AuthenticationError(
                "AUTH.TOKEN.INVALID", "Unable to refresh OIDC signing keys"
            ) from exc


class OidcTokenAuthenticator:
    def __init__(
        self,
        configuration: OidcConfiguration,
        *,
        client: httpx.AsyncClient | None = None,
        jwks_cache: SigningKeyCache | None = None,
    ) -> None:
        self._configuration = configuration
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        self._jwks_cache = jwks_cache or OidcJwksCache(configuration, self._client)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def authenticate(self, token: str) -> AuthenticationContext:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Invalid access token") from exc

        algorithm = header.get("alg")
        if algorithm not in self._configuration.allowed_algorithms:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Token algorithm is not allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Token signing key id is required")

        key = await self._jwks_cache.get(kid)
        key_algorithm = key.algorithm_name
        if (
            key_algorithm != algorithm
            or key_algorithm not in self._configuration.allowed_algorithms
        ):
            raise AuthenticationError(
                "AUTH.TOKEN.INVALID", "Signing key algorithm does not match token policy"
            )
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self._configuration.allowed_algorithms),
                audience=self._configuration.audience,
                issuer=self._configuration.issuer.rstrip("/"),
                leeway=self._configuration.clock_skew_seconds,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Invalid access token") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Token subject is required")
        audience = self._parse_audience(claims.get("aud"))
        expires_at = self._timestamp(claims.get("exp"), required=True)
        if expires_at is None:
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Token expiry is required")
        authenticated_at = self._timestamp(claims.get("auth_time"), required=False)
        scope_claim = claims.get("scope")
        scopes = frozenset(scope_claim.split()) if isinstance(scope_claim, str) else frozenset()
        amr_claim = claims.get("amr")
        amr = (
            tuple(value for value in amr_claim if isinstance(value, str))
            if isinstance(amr_claim, list)
            else ()
        )
        client_id = claims.get("azp") or claims.get("client_id")
        return AuthenticationContext(
            issuer=self._configuration.issuer.rstrip("/"),
            subject=subject,
            audience=audience,
            client_id=client_id if isinstance(client_id, str) else None,
            scopes=scopes,
            acr=claims.get("acr") if isinstance(claims.get("acr"), str) else None,
            amr=amr,
            authenticated_at=authenticated_at,
            token_id=claims.get("jti") if isinstance(claims.get("jti"), str) else None,
            expires_at=expires_at,
        )

    @staticmethod
    def _parse_audience(raw: Any) -> tuple[str, ...]:
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
            return tuple(raw)
        raise AuthenticationError("AUTH.TOKEN.INVALID", "Invalid token audience")

    @staticmethod
    def _timestamp(raw: Any, *, required: bool) -> datetime | None:
        if raw is None and not required:
            return None
        if not isinstance(raw, int | float):
            raise AuthenticationError("AUTH.TOKEN.INVALID", "Invalid token timestamp")
        return datetime.fromtimestamp(raw, tz=UTC)
