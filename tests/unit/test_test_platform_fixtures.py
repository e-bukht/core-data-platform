from __future__ import annotations

import asyncio
from datetime import datetime

from tests.test_platform.identity import CertificationIdentityProvider

from core_platform.platform_kernel.actor import Actor
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.policy import Capability, CapabilityGrant, PolicyRequest
from core_platform.platform_kernel.tenant import Tenant


def test_certification_kernel_fixtures_are_consistent(
    cert_instant: datetime,
    cert_tenant: Tenant,
    cert_actor: Actor,
    cert_authentication: AuthenticationContext,
    cert_capability: Capability,
    cert_capability_grant: CapabilityGrant,
    cert_policy_request: PolicyRequest,
    cert_execution_context: ExecutionContext,
) -> None:
    assert cert_tenant.active
    assert cert_actor.active
    assert cert_capability_grant.is_active_at(cert_instant)

    assert cert_capability_grant.tenant_id == cert_tenant.tenant_id
    assert cert_capability_grant.actor_id == cert_actor.actor_id
    assert cert_capability_grant.capability_id == cert_capability.capability_id

    assert cert_policy_request.tenant_id == cert_tenant.tenant_id
    assert cert_policy_request.actor_id == cert_actor.actor_id
    assert cert_policy_request.capability == cert_capability.code
    assert cert_policy_request.authentication_context == cert_authentication

    assert cert_execution_context.tenant_id == cert_tenant.tenant_id
    assert cert_execution_context.actor_id == cert_actor.actor_id
    assert cert_execution_context.authentication == cert_authentication

def test_certification_identity_provider_uses_real_oidc_authentication(
    cert_identity_provider: CertificationIdentityProvider,
) -> None:
    token = cert_identity_provider.issue_token()

    context = asyncio.run(
        cert_identity_provider.authenticate(token)
    )

    assert context.issuer == cert_identity_provider.issuer
    assert context.subject == "certification-actor"
    assert context.audience == (cert_identity_provider.audience,)
    assert context.client_id == "core-data-certification"
    assert context.scopes == frozenset({"openid", "profile"})
    assert context.acr == "urn:core-platform:acr:elevated"
    assert context.amr == ("pwd", "mfa")