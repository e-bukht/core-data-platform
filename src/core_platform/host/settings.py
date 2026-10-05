from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["local", "test", "ci", "staging", "prod"] = "local"

    log_level: str = "INFO"
    otel_enabled: bool = False
    otel_service_name: str = "core-data-platform"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_metric_export_interval_millis: int = Field(default=5000, ge=1000, le=60000)
    openapi_enabled: bool = True
    oidc_issuer: str = "http://localhost:8180/realms/core-data-platform"
    oidc_audience: str = "core-data-api"
    oidc_allowed_algorithms: str = "RS256"
    oidc_jwks_ttl_seconds: int = Field(default=300, gt=0, le=86400)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    tenant_header: str = "X-Tenant-Id"
    correlation_header: str = "X-Correlation-Id"
    evidence_signing_key_id: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="CORE_PLATFORM_",
        env_file=".env",
        env_file_encoding="utf-8",
        # Secret and connector providers may share the same .env file.
        # Settings validates only its own non-secret configuration surface.
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if not self.oidc_issuer.strip():
            raise ValueError("OIDC issuer must not be empty")
        if not self.oidc_audience.strip():
            raise ValueError("OIDC audience must not be empty")
        if self.environment in {"staging", "prod"} and not self.oidc_issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS outside local/test environments")
        key_id = self.evidence_signing_key_id
        if key_id is not None and (not key_id or key_id != key_id.strip()):
            raise ValueError("Evidence signing key ID must be non-empty and trimmed")
        return self

    @property
    def allowed_algorithms(self) -> tuple[str, ...]:
        values = tuple(
            item.strip() for item in self.oidc_allowed_algorithms.split(",") if item.strip()
        )
        if values != ("RS256",):
            raise ValueError("P0-I2 permits RS256 only; changing algorithms requires an ADR")
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
