from __future__ import annotations

import asyncio
import base64
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core_platform.application.break_glass import (
    BreakGlassLifecycleService,
    DurableBreakGlassActivationRecorder,
)
from core_platform.foundation.secrets import SecretProvider
from core_platform.foundation.temporal import UtcClock
from core_platform.host.break_glass_composition import (
    build_break_glass_activation_recorder,
    build_break_glass_runtime,
)
from core_platform.host.settings import Settings
from core_platform.infrastructure.persistence.break_glass_activation_persistence import (
    PostgresBreakGlassActivationPersistence,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.security.secret_catalog import (
    EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
)
from core_platform.infrastructure.security.secrets import EnvironmentSecretProvider


def _provider(value: str | None) -> EnvironmentSecretProvider:
    environment = {} if value is None else {"TEST_EVIDENCE_PRIVATE_KEY": value}
    return EnvironmentSecretProvider(
        bindings={
            EVIDENCE_SIGNING_PRIVATE_KEY_SECRET.name: "TEST_EVIDENCE_PRIVATE_KEY",
        },
        environ=environment,
    )


def test_factory_composes_real_ed25519_signer_and_atomic_persistence() -> None:
    key = Ed25519PrivateKey.generate()
    private_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    provider = _provider(base64.b64encode(private_der).decode("ascii"))
    database = Mock(spec=Database)
    recorder = build_break_glass_activation_recorder(
        settings=Settings(_env_file=None, evidence_signing_key_id="test-evidence-key-01"),
        secret_provider=provider,
        database=database,
    )

    assert isinstance(recorder, DurableBreakGlassActivationRecorder)
    assert isinstance(recorder._clock, UtcClock)
    assert isinstance(recorder._persistence, PostgresBreakGlassActivationPersistence)
    assert recorder._persistence._factory._database is database
    assert recorder._evidence_factory._signer.algorithm == "Ed25519"
    assert recorder._evidence_factory._signer.key_id == "test-evidence-key-01"

    signed = asyncio.run(recorder._evidence_factory._signer.sign(b"composition-test"))
    key.public_key().verify(signed, b"composition-test")


def test_factory_refuses_missing_key_id_without_accessing_secret() -> None:
    provider = Mock(spec=SecretProvider)
    with pytest.raises(RuntimeError, match="Evidence signing key ID is not configured"):
        build_break_glass_activation_recorder(
            settings=Settings(_env_file=None, evidence_signing_key_id=None),
            secret_provider=provider,
            database=Mock(spec=Database),
        )
    provider.get_secret.assert_not_called()


def test_factory_refuses_missing_private_key() -> None:
    with pytest.raises(RuntimeError, match="Secret is unavailable"):
        build_break_glass_activation_recorder(
            settings=Settings(_env_file=None, evidence_signing_key_id="test-evidence-key-01"),
            secret_provider=_provider(None),
            database=Mock(spec=Database),
        )


def test_factory_rejects_invalid_private_key_without_leaking_value() -> None:
    invalid_secret = "invalid-private-key-value-do-not-leak"
    with pytest.raises(RuntimeError, match="Evidence signing private key is invalid") as err:
        build_break_glass_activation_recorder(
            settings=Settings(_env_file=None, evidence_signing_key_id="test-evidence-key-01"),
            secret_provider=_provider(invalid_secret),
            database=Mock(spec=Database),
        )
    assert invalid_secret not in str(err.value)


# === C-I4-12ae SHARED RUNTIME ===


def test_runtime_composition_shares_signer_and_uow_factory() -> None:
    key = Ed25519PrivateKey.generate()

    private_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    provider = _provider(base64.b64encode(private_der).decode("ascii"))

    database = Mock(spec=Database)

    runtime = build_break_glass_runtime(
        settings=Settings(
            _env_file=None,
            evidence_signing_key_id="test-evidence-key-02",
        ),
        secret_provider=provider,
        database=database,
    )

    recorder = runtime.activation_recorder
    lifecycle = runtime.lifecycle_service

    assert isinstance(
        recorder,
        DurableBreakGlassActivationRecorder,
    )
    assert isinstance(
        lifecycle,
        BreakGlassLifecycleService,
    )

    from core_platform.infrastructure.persistence.break_glass_activation_persistence import (
        PostgresBreakGlassActivationPersistence,
    )
    from core_platform.infrastructure.persistence.break_glass_lifecycle_persistence import (
        PostgresBreakGlassLifecyclePersistence,
    )

    activation_persistence = recorder._persistence
    lifecycle_persistence = lifecycle._persistence
    assert isinstance(
        activation_persistence,
        PostgresBreakGlassActivationPersistence,
    )
    assert isinstance(
        lifecycle_persistence,
        PostgresBreakGlassLifecyclePersistence,
    )
    assert activation_persistence._factory is lifecycle_persistence._factory
    assert activation_persistence._factory._database is database

    assert recorder._evidence_factory._signer is lifecycle._evidence_factory._signer

    assert recorder._evidence_factory._signer.key_id == ("test-evidence-key-02")

    signed = asyncio.run(recorder._evidence_factory._signer.sign(b"shared-runtime-composition"))

    key.public_key().verify(
        signed,
        b"shared-runtime-composition",
    )
