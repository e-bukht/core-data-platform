from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["local", "test", "ci", "staging", "prod"] = "local"
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    log_level: str = "INFO"
    openapi_enabled: bool = True
    oidc_issuer: str = "http://localhost:8180/realms/core-data-platform"
    oidc_audience: str = "core-data-api"
    oidc_allowed_algorithms: str = "RS256"
    oidc_jwks_ttl_seconds: int = Field(default=300, gt=0, le=86400)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    tenant_header: str = "X-Tenant-Id"
    correlation_header: str = "X-Correlation-Id"

    model_config = SettingsConfigDict(
        env_prefix="CORE_PLATFORM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if not self.oidc_issuer.strip():
            raise ValueError("OIDC issuer must not be empty")
        if not self.oidc_audience.strip():
            raise ValueError("OIDC audience must not be empty")
        if self.environment in {"staging", "prod"} and not self.oidc_issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS outside local/test environments")
        return self

    @property
    def allowed_algorithms(self) -> tuple[str, ...]:
        values = tuple(
            item.strip() for item in self.oidc_allowed_algorithms.split(",") if item.strip()
        )
        if values != ("RS256",):
            raise ValueError("P0-I2 permits RS256 only; changing algorithms requires an ADR")
        return values

    def require_migration_database_url(self) -> str:
        if self.migration_database_url is None:
            raise RuntimeError("CORE_PLATFORM_MIGRATION_DATABASE_URL is required for migrations")
        return self.migration_database_url.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
