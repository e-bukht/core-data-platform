from __future__ import annotations

from pytest import MonkeyPatch

from core_platform.infrastructure.security.secret_catalog import (
    MIGRATION_DATABASE_URL_SECRET,
    RUNTIME_DATABASE_URL_SECRET,
    build_environment_secret_provider,
)


def test_database_secret_references_are_logical() -> None:
    assert (
        RUNTIME_DATABASE_URL_SECRET.name
        == "database/runtime-url"
    )
    assert (
        MIGRATION_DATABASE_URL_SECRET.name
        == "database/migration-url"
    )


def test_default_secret_provider_resolves_runtime_database(
    monkeypatch: MonkeyPatch,
) -> None:
    secret = (
        "postgresql+psycopg://"
        "runtime:runtime-secret@localhost/coredata"
    )

    monkeypatch.setenv(
        "CORE_PLATFORM_DATABASE_URL",
        secret,
    )

    provider = build_environment_secret_provider()

    resolved = provider.get_secret(
        RUNTIME_DATABASE_URL_SECRET
    )

    assert resolved.reveal_text() == secret
    assert "runtime-secret" not in repr(resolved)
    assert "runtime-secret" not in str(resolved)


def test_default_secret_provider_resolves_migration_database(
    monkeypatch: MonkeyPatch,
) -> None:
    secret = (
        "postgresql+psycopg://"
        "migrator:migration-secret@localhost/coredata"
    )

    monkeypatch.setenv(
        "CORE_PLATFORM_MIGRATION_DATABASE_URL",
        secret,
    )

    provider = build_environment_secret_provider()

    resolved = provider.get_secret(
        MIGRATION_DATABASE_URL_SECRET
    )

    assert resolved.reveal_text() == secret
    assert "migration-secret" not in repr(resolved)
    assert "migration-secret" not in str(resolved)