import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.errors import AuthorizationError, ValidationError
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import Actor, ActorStatus, ActorType
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, CapabilityId, GrantId, TenantId
from core_platform.platform_kernel.policy import CapabilityGrant, CapabilityGrantPdp, GrantStatus
from core_platform.platform_kernel.tenant import (
    MembershipStatus,
    Tenant,
    TenantMembership,
    TenantStatus,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000002"))
CAPABILITY_ID = CapabilityId(UUID("00000000-0000-7000-8000-000000000003"))
GRANT_ID = GrantId(UUID("00000000-0000-7000-8000-000000000004"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000005"))
NOW = datetime.now(UTC)


class FakeAuthenticator:
    async def authenticate(self, token: str) -> AuthenticationContext:
        assert token == "token"
        return AuthenticationContext(
            issuer="https://issuer.example",
            subject="subject",
            audience=("core-data-api",),
            client_id=None,
            scopes=frozenset(),
            acr=None,
            amr=(),
            authenticated_at=NOW,
            token_id=None,
            expires_at=NOW + timedelta(minutes=5),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.actor: Actor | None = Actor(
            ACTOR_ID, ActorType.HUMAN, ActorStatus.ACTIVE, "Alice", NOW, NOW
        )
        self.tenant: Tenant | None = Tenant(
            TENANT_ID, "tenant", "Tenant", TenantStatus.ACTIVE, NOW, NOW
        )
        self.membership: TenantMembership | None = TenantMembership(
            TENANT_ID, ACTOR_ID, MembershipStatus.ACTIVE, NOW - timedelta(minutes=1), None, 0
        )
        self.grant: CapabilityGrant | None = CapabilityGrant(
            GRANT_ID,
            TENANT_ID,
            ACTOR_ID,
            CAPABILITY_ID,
            "platform.context.read",
            NOW - timedelta(minutes=1),
            None,
            GrantStatus.ACTIVE,
        )

    async def resolve_actor(self, issuer: str, subject: str) -> Actor | None:
        return self.actor

    async def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
        return self.tenant

    async def get_membership(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> TenantMembership | None:
        return self.membership

    async def get_capability_grant(
        self, tenant_id: TenantId, actor_id: ActorId, capability_code: str
    ) -> CapabilityGrant | None:
        return self.grant

    async def list_active_capability_codes(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> tuple[str, ...]:
        return ("platform.context.read",)


def _service(repository: FakeRepository) -> ContextTrustService:
    return ContextTrustService(
        FakeAuthenticator(), repository, CapabilityGrantPdp(), environment="test"
    )


def test_authorize_builds_execution_context() -> None:
    repository = FakeRepository()
    context = asyncio.run(
        _service(repository).authorize(
            token="token",
            tenant_selector=str(TENANT_ID),
            capability_code="platform.context.read",
            correlation_id=CORRELATION_ID,
        )
    )
    assert context.tenant_id == TENANT_ID
    assert context.actor_id == ACTOR_ID


def test_unknown_identity_is_denied() -> None:
    repository = FakeRepository()
    repository.actor = None
    with pytest.raises(AuthorizationError, match="not registered"):
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )


def test_missing_tenant_context_is_validation_error() -> None:
    repository = FakeRepository()
    with pytest.raises(ValidationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=None,
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "TENANT.CONTEXT.REQUIRED"


def test_missing_capability_grant_is_default_deny() -> None:
    repository = FakeRepository()
    repository.grant = None
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "AUTHZ.CAPABILITY.DENIED"


def test_suspended_actor_is_denied() -> None:
    repository = FakeRepository()
    repository.actor = Actor(ACTOR_ID, ActorType.HUMAN, ActorStatus.SUSPENDED, "Alice", NOW, NOW)
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "ACTOR.NOT.ACTIVE"


def test_suspended_tenant_is_denied() -> None:
    repository = FakeRepository()
    repository.tenant = Tenant(TENANT_ID, "tenant", "Tenant", TenantStatus.SUSPENDED, NOW, NOW)
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "TENANT.NOT.ACTIVE"


def test_missing_membership_is_denied_without_tenant_enumeration() -> None:
    repository = FakeRepository()
    repository.membership = None
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "TENANT.ACCESS.DENIED"


def test_suspended_membership_is_denied_without_tenant_enumeration() -> None:
    repository = FakeRepository()
    repository.membership = TenantMembership(
        TENANT_ID,
        ACTOR_ID,
        MembershipStatus.SUSPENDED,
        NOW - timedelta(minutes=1),
        None,
        0,
    )
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
    assert caught.value.code == "TENANT.ACCESS.DENIED"


def test_invalid_tenant_identifier_is_rejected() -> None:
    repository = FakeRepository()

    with pytest.raises(ValidationError) as caught:
        asyncio.run(
            _service(repository).authorize(
                token="token",
                tenant_selector="not-a-uuid",
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )

    assert caught.value.code == "TENANT.ID.INVALID"
