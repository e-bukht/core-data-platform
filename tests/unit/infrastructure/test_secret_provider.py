from __future__ import annotations

import pytest

from core_platform.foundation.secrets import (
    SecretProvider,
    SecretReference,
)
from core_platform.infrastructure.security.secrets import (
    EnvironmentSecretProvider,
)


def _resolve(
    provider: SecretProvider,
    name: str,
) -> str:
    return provider.get_secret(SecretReference(name)).reveal_text()


def test_environment_provider_resolves_bound_secret() -> None:
    provider = EnvironmentSecretProvider(
        bindings={
            "database/runtime-url": "CORE_PLATFORM_DATABASE_URL",
        },
        environ={
            "CORE_PLATFORM_DATABASE_URL": "postgresql+psycopg://secret-value",
        },
    )

    assert (
        _resolve(
            provider,
            "database/runtime-url",
        )
        == "postgresql+psycopg://secret-value"
    )


def test_environment_provider_is_structural_secret_provider() -> None:
    provider: SecretProvider = EnvironmentSecretProvider(
        bindings={
            "test/secret": "TEST_SECRET",
        },
        environ={
            "TEST_SECRET": "value",
        },
    )

    assert provider.get_secret(SecretReference("test/secret")).reveal_text() == "value"


def test_environment_provider_rejects_unknown_reference() -> None:
    provider = EnvironmentSecretProvider(
        bindings={
            "known/secret": "KNOWN_SECRET",
        },
        environ={
            "KNOWN_SECRET": "classified",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Secret reference is not configured: unknown/secret",
    ) as exc_info:
        provider.get_secret(SecretReference("unknown/secret"))

    assert "classified" not in str(exc_info.value)


def test_environment_provider_rejects_missing_secret_without_leak() -> None:
    provider = EnvironmentSecretProvider(
        bindings={
            "evidence/private-key": "CORE_PLATFORM_EVIDENCE_PRIVATE_KEY",
        },
        environ={},
    )

    with pytest.raises(
        RuntimeError,
        match="Secret is unavailable: evidence/private-key",
    ) as exc_info:
        provider.get_secret(SecretReference("evidence/private-key"))

    assert "CORE_PLATFORM_EVIDENCE_PRIVATE_KEY" not in str(exc_info.value)


@pytest.mark.parametrize(
    "bindings",
    [
        {"": "SECRET_VAR"},
        {"   ": "SECRET_VAR"},
    ],
)
def test_environment_provider_rejects_blank_reference_binding(
    bindings: dict[str, str],
) -> None:
    with pytest.raises(
        ValueError,
        match=("Secret binding reference name must not be empty"),
    ):
        EnvironmentSecretProvider(
            bindings=bindings,
            environ={},
        )


@pytest.mark.parametrize(
    "bindings",
    [
        {"secret/ref": ""},
        {"secret/ref": "   "},
    ],
)
def test_environment_provider_rejects_blank_environment_binding(
    bindings: dict[str, str],
) -> None:
    with pytest.raises(
        ValueError,
        match=("Secret binding environment name must not be empty"),
    ):
        EnvironmentSecretProvider(
            bindings=bindings,
            environ={},
        )


def test_environment_provider_rejects_empty_secret_value() -> None:
    provider = EnvironmentSecretProvider(
        bindings={
            "test/secret": "TEST_SECRET",
        },
        environ={
            "TEST_SECRET": "",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Secret is unavailable: test/secret",
    ):
        provider.get_secret(SecretReference("test/secret"))
