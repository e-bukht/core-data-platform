from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from core_platform.foundation.secrets import (
    SecretProvider,
    SecretReference,
)


def load_ed25519_private_key(
    provider: SecretProvider,
    reference: SecretReference,
) -> Ed25519PrivateKey:
    encoded = provider.get_secret(
        reference
    ).reveal_bytes()

    try:
        der = base64.b64decode(
            encoded,
            validate=True,
        )

        private_key = serialization.load_der_private_key(
            der,
            password=None,
        )
    except (
        ValueError,
        TypeError,
        binascii.Error,
        UnsupportedAlgorithm,
    ):
        raise RuntimeError(
            "Evidence signing private key is invalid"
        ) from None

    if not isinstance(
        private_key,
        Ed25519PrivateKey,
    ):
        raise RuntimeError(
            "Evidence signing private key has unexpected type"
        )

    return private_key