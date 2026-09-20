import pytest
from pydantic import ValidationError as PydanticValidationError

from core_platform.host.settings import Settings

DATABASE_URL = "postgresql+psycopg://runtime:password@localhost:5432/coredata"


def test_p0_i2_allows_rs256_only() -> None:
    settings = Settings(database_url=DATABASE_URL, oidc_allowed_algorithms="RS256")
    assert settings.allowed_algorithms == ("RS256",)


def test_algorithm_change_requires_code_and_adr() -> None:
    settings = Settings(database_url=DATABASE_URL, oidc_allowed_algorithms="HS256")
    with pytest.raises(ValueError, match="RS256 only"):
        _ = settings.allowed_algorithms


def test_production_oidc_issuer_must_use_https() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            database_url=DATABASE_URL,
            environment="prod",
            oidc_issuer="http://issuer.example/realms/platform",
        )
