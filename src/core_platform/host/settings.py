from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["local", "test", "ci", "staging", "prod"] = "local"
    database_url: SecretStr
    log_level: str = "INFO"
    openapi_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CORE_PLATFORM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
