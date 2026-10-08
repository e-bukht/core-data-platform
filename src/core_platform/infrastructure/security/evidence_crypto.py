from __future__ import annotations

from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ED25519_ALGORITHM = "Ed25519"


class Ed25519EvidenceSigner:
    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        key_id: str,
    ) -> None:
        if not key_id.strip():
            raise ValueError("key_id must not be empty")

        self._private_key = private_key
        self._key_id = key_id

    @property
    def algorithm(self) -> str:
        return ED25519_ALGORITHM

    @property
    def key_id(self) -> str:
        return self._key_id

    async def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


class Ed25519EvidenceVerifier:
    def __init__(
        self,
        *,
        public_keys: Mapping[str, Ed25519PublicKey],
    ) -> None:
        if not public_keys:
            raise ValueError("public_keys must not be empty")

        if any(not key_id.strip() for key_id in public_keys):
            raise ValueError("public key identifiers must not be empty")

        self._public_keys = dict(public_keys)

    async def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool:
        if algorithm != ED25519_ALGORITHM:
            return False

        public_key = self._public_keys.get(key_id)
        if public_key is None:
            return False

        try:
            public_key.verify(signature, payload)
        except InvalidSignature:
            return False

        return True
