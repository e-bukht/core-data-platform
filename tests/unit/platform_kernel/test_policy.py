from datetime import UTC, datetime, timedelta
from uuid import UUID

from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, CapabilityId, GrantId, TenantId
from core_platform.platform_kernel.policy import (
    CapabilityGrant,
    CapabilityGrantPdp,
    GrantStatus,
    PolicyEffect,
    PolicyRequest,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000002"))
CAPABILITY_ID = CapabilityId(UUID("00000000-0000-7000-8000-000000000003"))
GRANT_ID = GrantId(UUID("00000000-0000-7000-8000-000000000004"))


def _auth(now: datetime) -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example",
        subject="subject",
        audience=("core-data-api",),
        client_id=None,
        scopes=frozenset(),
        acr=None,
        amr=(),
        authenticated_at=now,
        token_id=None,
        expires_at=now + timedelta(minutes=5),
    )


def test_pdp_is_default_deny() -> None:
    now = datetime.now(UTC)
    request = PolicyRequest(TENANT_ID, ACTOR_ID, "platform.context.read", "test", _auth(now))
    decision = CapabilityGrantPdp().decide(request, None)
    assert decision.effect is PolicyEffect.DENY


def test_pdp_allows_matching_active_grant() -> None:
    now = datetime.now(UTC)
    grant = CapabilityGrant(
        grant_id=GRANT_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        capability_id=CAPABILITY_ID,
        capability_code="platform.context.read",
        valid_from=now - timedelta(minutes=1),
        valid_until=None,
        status=GrantStatus.ACTIVE,
    )
    request = PolicyRequest(TENANT_ID, ACTOR_ID, "platform.context.read", "test", _auth(now))
    decision = CapabilityGrantPdp().decide(request, grant, now=now)
    assert decision.effect is PolicyEffect.ALLOW
