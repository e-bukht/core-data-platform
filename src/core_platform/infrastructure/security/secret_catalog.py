from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from core_platform.foundation.secrets import SecretReference
from core_platform.infrastructure.security.secrets import (
    EnvironmentSecretProvider,
)

RUNTIME_DATABASE_URL_SECRET = SecretReference("database/runtime-url")

MIGRATION_DATABASE_URL_SECRET = SecretReference("database/migration-url")

EVIDENCE_SIGNING_PRIVATE_KEY_SECRET = SecretReference("evidence/signing-private-key")

_SECRET_BINDINGS = {
    RUNTIME_DATABASE_URL_SECRET.name: "CORE_PLATFORM_DATABASE_URL",
    MIGRATION_DATABASE_URL_SECRET.name: "CORE_PLATFORM_MIGRATION_DATABASE_URL",
    EVIDENCE_SIGNING_PRIVATE_KEY_SECRET.name: "CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64",
}


class _SecretSourceSettings(BaseSettings):
    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    evidence_signing_private_key_b64: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_prefix="CORE_PLATFORM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def build_environment_secret_provider() -> EnvironmentSecretProvider:
    source = _SecretSourceSettings()

    resolved: dict[str, str] = {}

    if source.database_url is not None:
        resolved["CORE_PLATFORM_DATABASE_URL"] = source.database_url.get_secret_value()

    if source.migration_database_url is not None:
        resolved["CORE_PLATFORM_MIGRATION_DATABASE_URL"] = (
            source.migration_database_url.get_secret_value()
        )

    if source.evidence_signing_private_key_b64 is not None:
        resolved["CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64"] = (
            source.evidence_signing_private_key_b64.get_secret_value()
        )

    return EnvironmentSecretProvider(
        bindings=_SECRET_BINDINGS,
        environ=resolved,
    )
