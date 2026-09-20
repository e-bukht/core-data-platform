from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select

from core_platform.infrastructure.persistence.context_trust_schema import (
    actor,
    capability,
    capability_grant,
    external_identity,
    tenant,
    tenant_membership,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.platform_kernel.actor import Actor, ActorStatus, ActorType
from core_platform.platform_kernel.context_trust import ContextTrustRepository
from core_platform.platform_kernel.ids import ActorId, CapabilityId, GrantId, TenantId
from core_platform.platform_kernel.policy import CapabilityGrant, GrantStatus
from core_platform.platform_kernel.tenant import (
    MembershipStatus,
    Tenant,
    TenantMembership,
    TenantStatus,
)


class SqlContextTrustRepository(ContextTrustRepository):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def resolve_actor(self, issuer: str, subject: str) -> Actor | None:
        statement = (
            select(actor)
            .select_from(external_identity.join(actor, external_identity.c.actor_id == actor.c.id))
            .where(
                and_(
                    external_identity.c.issuer == issuer,
                    external_identity.c.subject == subject,
                    external_identity.c.status == "ACTIVE",
                )
            )
        )
        async with self._database.transaction() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return Actor(
            actor_id=ActorId(row["id"]),
            actor_type=ActorType(row["actor_type"]),
            status=ActorStatus(row["status"]),
            display_name=row["display_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
        statement = select(tenant).where(tenant.c.id == tenant_id.value)
        async with self._database.transaction() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return Tenant(
            tenant_id=TenantId(row["id"]),
            code=row["code"],
            display_name=row["display_name"],
            status=TenantStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_membership(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> TenantMembership | None:
        statement = select(tenant_membership).where(
            and_(
                tenant_membership.c.tenant_id == tenant_id.value,
                tenant_membership.c.actor_id == actor_id.value,
            )
        )
        async with self._database.tenant_transaction(tenant_id.value) as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return TenantMembership(
            tenant_id=TenantId(row["tenant_id"]),
            actor_id=ActorId(row["actor_id"]),
            status=MembershipStatus(row["status"]),
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            version=row["version"],
        )

    async def get_capability_grant(
        self, tenant_id: TenantId, actor_id: ActorId, capability_code: str
    ) -> CapabilityGrant | None:
        statement = (
            select(
                capability_grant.c.id,
                capability_grant.c.tenant_id,
                capability_grant.c.actor_id,
                capability_grant.c.capability_id,
                capability_grant.c.status,
                capability_grant.c.valid_from,
                capability_grant.c.valid_until,
                capability.c.code.label("capability_code"),
            )
            .select_from(
                capability_grant.join(
                    capability, capability_grant.c.capability_id == capability.c.id
                )
            )
            .where(
                and_(
                    capability_grant.c.tenant_id == tenant_id.value,
                    capability_grant.c.actor_id == actor_id.value,
                    capability.c.code == capability_code,
                    capability.c.status == "ACTIVE",
                )
            )
        )
        async with self._database.tenant_transaction(tenant_id.value) as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return CapabilityGrant(
            grant_id=GrantId(row["id"]),
            tenant_id=TenantId(row["tenant_id"]),
            actor_id=ActorId(row["actor_id"]),
            capability_id=CapabilityId(row["capability_id"]),
            capability_code=row["capability_code"],
            status=GrantStatus(row["status"]),
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
        )

    async def list_active_capability_codes(
        self, tenant_id: TenantId, actor_id: ActorId
    ) -> tuple[str, ...]:
        now = datetime.now(UTC)
        statement = (
            select(capability.c.code)
            .select_from(
                capability_grant.join(
                    capability, capability_grant.c.capability_id == capability.c.id
                )
            )
            .where(
                and_(
                    capability_grant.c.tenant_id == tenant_id.value,
                    capability_grant.c.actor_id == actor_id.value,
                    capability_grant.c.status == "ACTIVE",
                    capability.c.status == "ACTIVE",
                    capability_grant.c.valid_from <= now,
                    (capability_grant.c.valid_until.is_(None))
                    | (capability_grant.c.valid_until > now),
                )
            )
            .order_by(capability.c.code)
        )
        async with self._database.tenant_transaction(tenant_id.value) as connection:
            rows = (await connection.execute(statement)).scalars().all()
        return tuple(rows)
