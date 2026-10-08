import pytest
from pydantic import ValidationError as PydanticValidationError

from core_platform.host.settings import Settings


def test_p0_i2_allows_rs256_only() -> None:
    settings = Settings(oidc_allowed_algorithms="RS256")
    assert settings.allowed_algorithms == ("RS256",)


def test_algorithm_change_requires_code_and_adr() -> None:
    settings = Settings(oidc_allowed_algorithms="HS256")
    with pytest.raises(ValueError, match="RS256 only"):
        _ = settings.allowed_algorithms


def test_production_oidc_issuer_must_use_https() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            environment="prod",
            oidc_issuer="http://issuer.example/realms/platform",
        )


def test_evidence_signing_key_id_is_configurable() -> None:
    settings = Settings(
        _env_file=None,
        evidence_signing_key_id="local-ed25519-01",
    )
    assert settings.evidence_signing_key_id == "local-ed25519-01"


@pytest.mark.parametrize("key_id", ["", "   ", " invalid "])
def test_evidence_signing_key_id_rejects_invalid_values(key_id: str) -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            _env_file=None,
            evidence_signing_key_id=key_id,
        )
