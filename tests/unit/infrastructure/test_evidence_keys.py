from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from pytest import MonkeyPatch

from core_platform.infrastructure.security.evidence_keys import (
    load_ed25519_private_key,
)
from core_platform.infrastructure.security.secret_catalog import (
    EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
    build_environment_secret_provider,
)


def _encoded_private_key() -> str:
    private_key = Ed25519PrivateKey.generate()

    der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return base64.b64encode(
        der
    ).decode("ascii")


def test_evidence_signing_secret_reference_is_logical() -> None:
    assert (
        EVIDENCE_SIGNING_PRIVATE_KEY_SECRET.name
        == "evidence/signing-private-key"
    )


def test_ed25519_private_key_loads_through_secret_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    encoded = _encoded_private_key()

    monkeypatch.setenv(
        "CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64",
        encoded,
    )

    provider = build_environment_secret_provider()

    private_key = load_ed25519_private_key(
        provider,
        EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
    )

    payload = b"evidence-envelope"
    signature = private_key.sign(payload)

    private_key.public_key().verify(
        signature,
        payload,
    )


def test_invalid_base64_does_not_leak_secret(
    monkeypatch: MonkeyPatch,
) -> None:
    secret = "definitely-not-valid-base64!!!"

    monkeypatch.setenv(
        "CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64",
        secret,
    )

    provider = build_environment_secret_provider()

    with pytest.raises(
        RuntimeError,
        match="Evidence signing private key is invalid",
    ) as exc_info:
        load_ed25519_private_key(
            provider,
            EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
        )

    assert secret not in str(exc_info.value)


def test_valid_base64_with_invalid_key_material_is_rejected(
    monkeypatch: MonkeyPatch,
) -> None:
    raw_secret = b"not-a-pkcs8-private-key"
    encoded = base64.b64encode(
        raw_secret
    ).decode("ascii")

    monkeypatch.setenv(
        "CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64",
        encoded,
    )

    provider = build_environment_secret_provider()

    with pytest.raises(
        RuntimeError,
        match="Evidence signing private key is invalid",
    ) as exc_info:
        load_ed25519_private_key(
            provider,
            EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
        )

    assert encoded not in str(exc_info.value)
    assert raw_secret.decode("ascii") not in str(
        exc_info.value
    )