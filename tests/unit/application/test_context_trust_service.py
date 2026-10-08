import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from core_platform.application.break_glass import BreakGlassActivationRecorder
from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.errors import AuthorizationError, ValidationError
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import Actor, ActorStatus, ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    CapabilityId,
    GrantId,
    TenantId,
)
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
            acr="urn:core-platform:acr:elevated",
            amr=("pwd", "mfa"),
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


class FakeBreakGlassRepository:
    def __init__(self) -> None:
        self.grants: tuple[BreakGlassGrant, ...] = ()
        self.calls = 0

    async def list_candidate_grants(
        self,
        tenant_id: TenantId,
        actor_id: ActorId,
        capability: str,
        *,
        now: datetime,
    ) -> tuple[BreakGlassGrant, ...]:
        self.calls += 1
        return self.grants


def _service(
    repository: FakeRepository,
    break_glass_repository: FakeBreakGlassRepository | None = None,
    recorder: BreakGlassActivationRecorder | None = None,
) -> ContextTrustService:
    return ContextTrustService(
        authenticator=FakeAuthenticator(),
        repository=repository,
        break_glass_repository=(break_glass_repository or FakeBreakGlassRepository()),
        pdp=CapabilityGrantPdp(),
        environment="test",
        break_glass_activation_recorder=(
            recorder if recorder is not None else AsyncMock(spec=BreakGlassActivationRecorder)
        ),
    )


DEFAULT_BREAK_GLASS_GRANT_ID = UUID("00000000-0000-7000-8000-000000000006")


def _break_glass_grant(
    *,
    scope: BreakGlassScope | None = None,
    grant_id: UUID = DEFAULT_BREAK_GLASS_GRANT_ID,
) -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=BreakGlassGrantId(grant_id),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        issued_by_actor_id=ActorId(UUID("00000000-0000-7000-8000-000000000007")),
        capabilities=("platform.context.read",),
        scope=(scope or BreakGlassScope(BreakGlassScopeKind.TENANT)),
        reason="Emergency recovery",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        status=BreakGlassGrantStatus.ACTIVE,
        accepted_acr_values=frozenset(
            {
                "urn:core-platform:acr:elevated",
            }
        ),
        required_amr=frozenset(
            {
                "mfa",
            }
        ),
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


def test_normal_allow_does_not_query_break_glass() -> None:
    repository = FakeRepository()
    break_glass_repository = FakeBreakGlassRepository()
    break_glass_repository.grants = (_break_glass_grant(),)

    recorder = AsyncMock(spec=BreakGlassActivationRecorder)
    context = asyncio.run(
        _service(
            repository,
            break_glass_repository,
            recorder,
        ).authorize(
            token="token",
            tenant_selector=str(TENANT_ID),
            capability_code="platform.context.read",
            correlation_id=CORRELATION_ID,
        )
    )

    assert context.break_glass is None
    assert break_glass_repository.calls == 0
    recorder.record.assert_not_awaited()


def test_break_glass_can_authorize_after_normal_deny() -> None:
    repository = FakeRepository()
    repository.grant = None

    break_glass_repository = FakeBreakGlassRepository()
    break_glass_repository.grants = (_break_glass_grant(),)

    recorder = AsyncMock(spec=BreakGlassActivationRecorder)
    context = asyncio.run(
        _service(
            repository,
            break_glass_repository,
            recorder,
        ).authorize(
            token="token",
            tenant_selector=str(TENANT_ID),
            capability_code="platform.context.read",
            correlation_id=CORRELATION_ID,
        )
    )

    assert break_glass_repository.calls == 1
    recorder.record.assert_awaited_once_with(context)
    assert context.break_glass is not None
    assert context.break_glass.capability == ("platform.context.read")
    assert context.break_glass.reason == ("Emergency recovery")


def test_break_glass_evaluates_candidates_until_allow() -> None:
    repository = FakeRepository()
    repository.grant = None

    break_glass_repository = FakeBreakGlassRepository()

    wrong_scope = _break_glass_grant(
        scope=BreakGlassScope(
            BreakGlassScopeKind.RESOURCE,
            resource_type="outbox-message",
            resource_id="message-other",
        ),
        grant_id=UUID("00000000-0000-7000-8000-000000000008"),
    )

    exact_scope = _break_glass_grant(
        scope=BreakGlassScope(
            BreakGlassScopeKind.RESOURCE,
            resource_type="outbox-message",
            resource_id="message-1",
        ),
        grant_id=UUID("00000000-0000-7000-8000-000000000009"),
    )

    break_glass_repository.grants = (
        wrong_scope,
        exact_scope,
    )

    context = asyncio.run(
        _service(
            repository,
            break_glass_repository,
        ).authorize(
            token="token",
            tenant_selector=str(TENANT_ID),
            capability_code="platform.context.read",
            correlation_id=CORRELATION_ID,
            resource_type="outbox-message",
            resource_id="message-1",
        )
    )

    assert context.break_glass is not None
    assert context.break_glass.grant_id == exact_scope.grant_id
    assert context.break_glass.scope.resource_id == ("message-1")


def test_break_glass_deny_preserves_default_deny() -> None:
    repository = FakeRepository()
    repository.grant = None

    break_glass_repository = FakeBreakGlassRepository()
    break_glass_repository.grants = (
        _break_glass_grant(
            scope=BreakGlassScope(
                BreakGlassScopeKind.RESOURCE,
                resource_type="outbox-message",
                resource_id="message-other",
            )
        ),
    )

    recorder = AsyncMock(spec=BreakGlassActivationRecorder)
    with pytest.raises(AuthorizationError) as caught:
        asyncio.run(
            _service(
                repository,
                break_glass_repository,
                recorder,
            ).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
                resource_type="outbox-message",
                resource_id="message-1",
            )
        )

    assert caught.value.code == ("AUTHZ.CAPABILITY.DENIED")
    assert break_glass_repository.calls == 1
    recorder.record.assert_not_awaited()


def test_break_glass_recorder_failure_is_fail_closed() -> None:
    repository = FakeRepository()
    repository.grant = None
    break_glass_repository = FakeBreakGlassRepository()
    break_glass_repository.grants = (_break_glass_grant(),)
    recorder = AsyncMock(spec=BreakGlassActivationRecorder)
    recorder.record.side_effect = RuntimeError("activation persistence failed")

    with pytest.raises(RuntimeError, match="activation persistence failed"):
        asyncio.run(
            _service(repository, break_glass_repository, recorder).authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )

    recorder.record.assert_awaited_once()
    context = recorder.record.await_args.args[0]
    assert context.break_glass is not None


def test_missing_recorder_is_fail_closed_for_break_glass() -> None:
    repository = FakeRepository()
    repository.grant = None
    break_glass_repository = FakeBreakGlassRepository()
    break_glass_repository.grants = (_break_glass_grant(),)
    service = ContextTrustService(
        authenticator=FakeAuthenticator(),
        repository=repository,
        break_glass_repository=break_glass_repository,
        pdp=CapabilityGrantPdp(),
        environment="test",
    )

    with pytest.raises(RuntimeError, match="recorder is not configured"):
        asyncio.run(
            service.authorize(
                token="token",
                tenant_selector=str(TENANT_ID),
                capability_code="platform.context.read",
                correlation_id=CORRELATION_ID,
            )
        )
