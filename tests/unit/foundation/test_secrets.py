from __future__ import annotations

import pytest

from core_platform.foundation.secrets import (
    SecretProvider,
    SecretReference,
    SecretValue,
)


class _FakeSecretProvider:
    def __init__(
        self,
        value: SecretValue,
    ) -> None:
        self._value = value
        self.last_reference: SecretReference | None = None

    def get_secret(
        self,
        reference: SecretReference,
    ) -> SecretValue:
        self.last_reference = reference
        return self._value


def _resolve(
    provider: SecretProvider,
    reference: SecretReference,
) -> SecretValue:
    return provider.get_secret(reference)


def test_secret_reference_normalizes_name() -> None:
    reference = SecretReference("  evidence/signing/current  ")

    assert reference.name == "evidence/signing/current"


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        "\t",
    ],
)
def test_secret_reference_rejects_empty_name(
    name: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Secret reference name must not be empty",
    ):
        SecretReference(name)


def test_secret_value_requires_explicit_reveal() -> None:
    secret = SecretValue("private-material")

    assert secret.reveal_text() == "private-material"
    assert secret.reveal_bytes() == b"private-material"

    assert "private-material" not in str(secret)
    assert "private-material" not in repr(secret)

    assert str(secret) == "<redacted>"
    assert repr(secret) == "SecretValue(<redacted>)"


def test_secret_value_accepts_binary_material() -> None:
    secret = SecretValue(b"\x00\x01\x02\xff")

    assert secret.reveal_bytes() == b"\x00\x01\x02\xff"


@pytest.mark.parametrize(
    "value",
    [
        "",
        b"",
    ],
)
def test_secret_value_rejects_empty_material(
    value: str | bytes,
) -> None:
    with pytest.raises(
        ValueError,
        match="Secret value must not be empty",
    ):
        SecretValue(value)


def test_secret_provider_is_structural_port() -> None:
    secret = SecretValue("resolved-secret")
    provider = _FakeSecretProvider(secret)
    reference = SecretReference("database/runtime-url")

    resolved = _resolve(
        provider,
        reference,
    )

    assert resolved is secret
    assert provider.last_reference == reference
