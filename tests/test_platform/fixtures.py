from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import Actor, ActorStatus, ActorType
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    CapabilityId,
    GrantId,
    TenantId,
)
from core_platform.platform_kernel.policy import (
    Capability,
    CapabilityGrant,
    CapabilityStatus,
    GrantStatus,
    PolicyRequest,
    RiskClass,
)
from core_platform.platform_kernel.tenant import Tenant, TenantStatus
from tests.test_platform.identity import CertificationIdentityProvider

_CERT_INSTANT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-00000000c101"))
_ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-00000000c102"))
_CAPABILITY_ID = CapabilityId(UUID("00000000-0000-7000-8000-00000000c103"))
_GRANT_ID = GrantId(UUID("00000000-0000-7000-8000-00000000c104"))
_CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-00000000c105"))
_CAPABILITY_CODE = "platform.certification.read"


@pytest.fixture
def cert_instant() -> datetime:
    return _CERT_INSTANT


@pytest.fixture
def cert_tenant(cert_instant: datetime) -> Tenant:
    return Tenant(
        tenant_id=_TENANT_ID,
        code="cert-tenant",
        display_name="Certification Tenant",
        status=TenantStatus.ACTIVE,
        created_at=cert_instant,
        updated_at=cert_instant,
    )


@pytest.fixture
def cert_actor(cert_instant: datetime) -> Actor:
    return Actor(
        actor_id=_ACTOR_ID,
        actor_type=ActorType.HUMAN,
        status=ActorStatus.ACTIVE,
        display_name="Certification Actor",
        created_at=cert_instant,
        updated_at=cert_instant,
    )


@pytest.fixture
def cert_authentication(cert_instant: datetime) -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.certification.test",
        subject="certification-actor",
        audience=("core-data-api",),
        client_id="core-data-certification",
        scopes=frozenset({"openid", "profile"}),
        acr="urn:core-platform:acr:elevated",
        amr=("pwd", "mfa"),
        authenticated_at=cert_instant,
        token_id="certification-token",
        expires_at=cert_instant + timedelta(minutes=15),
    )


@pytest.fixture
def cert_capability() -> Capability:
    return Capability(
        capability_id=_CAPABILITY_ID,
        code=_CAPABILITY_CODE,
        description="Reusable certification capability",
        risk_class=RiskClass.HIGH,
        status=CapabilityStatus.ACTIVE,
    )


@pytest.fixture
def cert_capability_grant(
    cert_instant: datetime,
    cert_tenant: Tenant,
    cert_actor: Actor,
    cert_capability: Capability,
) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=_GRANT_ID,
        tenant_id=cert_tenant.tenant_id,
        actor_id=cert_actor.actor_id,
        capability_id=cert_capability.capability_id,
        capability_code=cert_capability.code,
        valid_from=cert_instant - timedelta(minutes=1),
        valid_until=cert_instant + timedelta(hours=1),
        status=GrantStatus.ACTIVE,
    )


@pytest.fixture
def cert_policy_request(
    cert_tenant: Tenant,
    cert_actor: Actor,
    cert_capability: Capability,
    cert_authentication: AuthenticationContext,
) -> PolicyRequest:
    return PolicyRequest(
        tenant_id=cert_tenant.tenant_id,
        actor_id=cert_actor.actor_id,
        capability=cert_capability.code,
        environment="test",
        authentication_context=cert_authentication,
    )


@pytest.fixture
def cert_execution_context(
    cert_tenant: Tenant,
    cert_actor: Actor,
    cert_authentication: AuthenticationContext,
) -> ExecutionContext:
    return ExecutionContext(
        tenant_id=cert_tenant.tenant_id,
        actor_id=cert_actor.actor_id,
        actor_type=cert_actor.actor_type,
        authentication=cert_authentication,
        correlation_id=_CORRELATION_ID,
    )


@pytest.fixture
def cert_identity_provider() -> CertificationIdentityProvider:
    return CertificationIdentityProvider.create()
