from datetime import UTC, datetime

from core_platform.platform_kernel.identity import (
    ExternalIdentity,
    ExternalIdentityProviderType,
    ExternalIdentityStatus,
)
from core_platform.platform_kernel.ids import ActorId, IdentityId


def test_external_identity_models_oidc_provider_explicitly() -> None:
    identity = ExternalIdentity(
        identity_id=IdentityId.new(),
        provider_type=ExternalIdentityProviderType.OIDC,
        issuer="https://issuer.example",
        subject="subject-1",
        actor_id=ActorId.new(),
        status=ExternalIdentityStatus.ACTIVE,
        metadata={"linked_at": datetime.now(UTC).isoformat()},
    )

    assert identity.provider_type is ExternalIdentityProviderType.OIDC
