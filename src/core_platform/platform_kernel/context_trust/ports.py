from __future__ import annotations

from typing import Protocol

from core_platform.platform_kernel.actor import Actor
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.platform_kernel.policy import CapabilityGrant
from core_platform.platform_kernel.tenant import Tenant, TenantMembership


class ContextTrustRepository(Protocol):
    async def resolve_actor(self, issuer: str, subject: str) -> Actor | None: ...

    async def get_tenant(self, tenant_id: TenantId) -> Tenant | None: ...

    async def get_membership(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> TenantMembership | None: ...

    async def get_capability_grant(
        self, tenant_id: TenantId, actor_id: ActorId, capability_code: str
    ) -> CapabilityGrant | None: ...

    async def list_active_capability_codes(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> tuple[str, ...]: ...
