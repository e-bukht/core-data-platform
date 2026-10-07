from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jwt import PyJWK

from core_platform.foundation.errors import AuthenticationError
from core_platform.infrastructure.security.oidc import (
    OidcConfiguration,
    OidcTokenAuthenticator,
)
from core_platform.platform_kernel.identity import AuthenticationContext


class CertificationIdentityProvider:
    """In-process OIDC identity provider for certification scenarios."""

    def __init__(
        self,
        private_key: RSAPrivateKey,
        public_key: PyJWK,
        *,
        issuer: str,
        audience: str,
        key_id: str,
    ) -> None:
        self._private_key = private_key
        self._public_key = public_key
        self.issuer = issuer
        self.audience = audience
        self.key_id = key_id

    @classmethod
    def create(cls) -> CertificationIdentityProvider:
        issuer = "https://identity.certification.test"
        audience = "core-data-api"
        key_id = "certification-rs256"

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
            private_key.public_key(),
            as_dict=True,
        )
        public_jwk["kid"] = key_id
        public_jwk["alg"] = "RS256"
        public_jwk["use"] = "sig"

        return cls(
            private_key,
            PyJWK.from_dict(public_jwk),
            issuer=issuer,
            audience=audience,
            key_id=key_id,
        )

    async def get(self, kid: str) -> PyJWK:
        if kid != self.key_id:
            raise AuthenticationError(
                "AUTH.TOKEN.INVALID",
                "Unknown certification signing key",
            )
        return self._public_key

    def issue_token(
        self,
        *,
        subject: str = "certification-actor",
        client_id: str = "core-data-certification",
        scopes: tuple[str, ...] = ("openid", "profile"),
        acr: str = "urn:core-platform:acr:elevated",
        amr: tuple[str, ...] = ("pwd", "mfa"),
    ) -> str:
        now = datetime.now(UTC)

        claims: dict[str, object] = {
            "iss": self.issuer,
            "sub": subject,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "auth_time": int(now.timestamp()),
            "scope": " ".join(scopes),
            "azp": client_id,
            "acr": acr,
            "amr": list(amr),
            "jti": "certification-token",
        }

        return jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )

    async def authenticate(self, token: str) -> AuthenticationContext:
        authenticator = OidcTokenAuthenticator(
            OidcConfiguration(
                issuer=self.issuer,
                audience=self.audience,
                allowed_algorithms=("RS256",),
                jwks_ttl_seconds=300,
                clock_skew_seconds=30,
            ),
            jwks_cache=self,
        )
        try:
            return await authenticator.authenticate(token)
        finally:
            await authenticator.close()