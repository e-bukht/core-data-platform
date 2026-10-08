from __future__ import annotations

import asyncio

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from core_platform.infrastructure.security.evidence_crypto import (
    ED25519_ALGORITHM,
    Ed25519EvidenceSigner,
    Ed25519EvidenceVerifier,
)


def test_ed25519_signature_verifies_with_matching_key() -> None:
    async def run() -> None:
        private_key = Ed25519PrivateKey.generate()

        signer = Ed25519EvidenceSigner(
            private_key=private_key,
            key_id="evidence-key-2026-01",
        )
        verifier = Ed25519EvidenceVerifier(
            public_keys={
                "evidence-key-2026-01": private_key.public_key(),
            }
        )

        payload = b"canonical-evidence-envelope"
        signature = await signer.sign(payload)

        assert signer.algorithm == ED25519_ALGORITHM
        assert signer.key_id == "evidence-key-2026-01"

        assert await verifier.verify(
            payload,
            signature=signature,
            algorithm=signer.algorithm,
            key_id=signer.key_id,
        )

    asyncio.run(run())


def test_ed25519_verifier_detects_payload_tampering() -> None:
    async def run() -> None:
        private_key = Ed25519PrivateKey.generate()
        signer = Ed25519EvidenceSigner(
            private_key=private_key,
            key_id="key-1",
        )
        verifier = Ed25519EvidenceVerifier(public_keys={"key-1": private_key.public_key()})

        signature = await signer.sign(b"original")

        assert not await verifier.verify(
            b"tampered",
            signature=signature,
            algorithm=ED25519_ALGORITHM,
            key_id="key-1",
        )

    asyncio.run(run())


def test_ed25519_verifier_does_not_fallback_to_another_key() -> None:
    async def run() -> None:
        signing_key = Ed25519PrivateKey.generate()
        other_key = Ed25519PrivateKey.generate()

        signer = Ed25519EvidenceSigner(
            private_key=signing_key,
            key_id="signing-key",
        )
        verifier = Ed25519EvidenceVerifier(
            public_keys={
                "signing-key": signing_key.public_key(),
                "other-key": other_key.public_key(),
            }
        )

        payload = b"evidence"
        signature = await signer.sign(payload)

        assert not await verifier.verify(
            payload,
            signature=signature,
            algorithm=ED25519_ALGORITHM,
            key_id="unknown-key",
        )

        assert not await verifier.verify(
            payload,
            signature=signature,
            algorithm=ED25519_ALGORITHM,
            key_id="other-key",
        )

    asyncio.run(run())


def test_ed25519_verifier_rejects_unsupported_algorithm() -> None:
    async def run() -> None:
        private_key = Ed25519PrivateKey.generate()
        signer = Ed25519EvidenceSigner(
            private_key=private_key,
            key_id="key-1",
        )
        verifier = Ed25519EvidenceVerifier(public_keys={"key-1": private_key.public_key()})

        payload = b"evidence"
        signature = await signer.sign(payload)

        assert not await verifier.verify(
            payload,
            signature=signature,
            algorithm="RS256",
            key_id="key-1",
        )

    asyncio.run(run())


def test_ed25519_signer_rejects_blank_key_id() -> None:
    with pytest.raises(
        ValueError,
        match="key_id must not be empty",
    ):
        Ed25519EvidenceSigner(
            private_key=Ed25519PrivateKey.generate(),
            key_id="   ",
        )


def test_ed25519_verifier_requires_configured_public_keys() -> None:
    with pytest.raises(
        ValueError,
        match="public_keys must not be empty",
    ):
        Ed25519EvidenceVerifier(public_keys={})
