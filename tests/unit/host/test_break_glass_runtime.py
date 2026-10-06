from __future__ import annotations

import asyncio
import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core_platform.application.break_glass import (
    BreakGlassLifecycleService,
    DurableBreakGlassActivationRecorder,
)
from core_platform.host.main import create_app
from core_platform.host.settings import Settings
from core_platform.infrastructure.observability import (
    ObservabilityConfig,
    ObservabilityRuntime,
)
from core_platform.infrastructure.security.secret_catalog import (
    EVIDENCE_SIGNING_PRIVATE_KEY_SECRET,
    RUNTIME_DATABASE_URL_SECRET,
)
from core_platform.infrastructure.security.secrets import EnvironmentSecretProvider

_DB_URL = "postgresql+psycopg://unused:unused@localhost:5434/unused"


def _secret_provider(key: str | None) -> EnvironmentSecretProvider:
    values = {"TEST_RUNTIME_DB_URL": _DB_URL}
    if key is not None:
        values["TEST_EVIDENCE_SIGNING_KEY"] = key
    return EnvironmentSecretProvider(
        bindings={
            RUNTIME_DATABASE_URL_SECRET.name: "TEST_RUNTIME_DB_URL",
            EVIDENCE_SIGNING_PRIVATE_KEY_SECRET.name: "TEST_EVIDENCE_SIGNING_KEY",
        },
        environ=values,
    )


def _encoded_private_key() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


def _runtime() -> ObservabilityRuntime:
    return ObservabilityRuntime(
        ObservabilityConfig(
            enabled=False,
            service_name="core-data-platform-test",
            service_version="test",
            environment="test",
            otlp_endpoint="http://unused.invalid:4318",
            trace_sample_ratio=1.0,
            metric_export_interval_millis=5000,
        )
    )


def test_runtime_injects_real_durable_recorder() -> None:
    app = create_app(
        settings=Settings(_env_file=None, evidence_signing_key_id="test-key-01"),
        secret_provider=_secret_provider(_encoded_private_key()),
        observability=_runtime(),
    )

    async def verify() -> None:
        async with app.router.lifespan_context(app):
            service = app.state.context_trust
            recorder = service._break_glass_activation_recorder
            lifecycle = app.state.break_glass_lifecycle

            assert isinstance(
                recorder,
                DurableBreakGlassActivationRecorder,
            )
            assert isinstance(
                lifecycle,
                BreakGlassLifecycleService,
            )

            assert recorder._evidence_factory._signer.key_id == "test-key-01"

            assert (
                recorder._persistence._factory
                is lifecycle._persistence._factory
            )
            assert (
                recorder._persistence._factory._database
                is app.state.database
            )
            assert (
                recorder._persistence._factory._metrics
                is app.state.observability.metrics
            )
            assert (
                recorder._evidence_factory._signer
                is lifecycle._evidence_factory._signer
            )

            assert app.state.startup_complete is True
        assert app.state.startup_complete is False

    asyncio.run(verify())


def test_runtime_missing_key_id_fails_startup_and_disposes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core_platform.host import main

    original_close = main.Database.close
    closed = []

    async def tracked_close(database: main.Database) -> None:
        closed.append(True)
        await original_close(database)

    monkeypatch.setattr(main.Database, "close", tracked_close)
    app = create_app(
        settings=Settings(_env_file=None, evidence_signing_key_id=None),
        secret_provider=_secret_provider(_encoded_private_key()),
        observability=_runtime(),
    )

    async def verify() -> None:
        with pytest.raises(RuntimeError, match="Evidence signing key ID is not configured"):
            async with app.router.lifespan_context(app):
                pytest.fail("Startup must refuse missing key ID")

    asyncio.run(verify())
    assert closed == [True]
    assert app.state.startup_complete is False
    assert not hasattr(app.state, "context_trust")


@pytest.mark.parametrize(
    ("bad_key", "expected_error"),
    [
        (None, "Secret is unavailable"),
        ("invalid-runtime-private-key-do-not-leak", "Evidence signing private key is invalid"),
    ],
)
def test_runtime_unavailable_or_invalid_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    bad_key: str | None,
    expected_error: str,
) -> None:
    from core_platform.host import main

    original_close = main.Database.close
    closed = []

    async def tracked_close(database: main.Database) -> None:
        closed.append(True)
        await original_close(database)

    monkeypatch.setattr(main.Database, "close", tracked_close)
    app = create_app(
        settings=Settings(_env_file=None, evidence_signing_key_id="test-key-01"),
        secret_provider=_secret_provider(bad_key),
        observability=_runtime(),
    )

    async def verify() -> None:
        with pytest.raises(RuntimeError, match=expected_error) as exc:
            async with app.router.lifespan_context(app):
                pytest.fail("Startup must refuse missing or invalid private key")
        if bad_key is not None:
            assert bad_key not in str(exc.value)

    asyncio.run(verify())
    assert closed == [True]
    assert app.state.startup_complete is False
    assert not hasattr(app.state, "context_trust")
