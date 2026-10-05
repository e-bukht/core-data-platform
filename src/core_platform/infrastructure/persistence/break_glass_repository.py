from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, any_, select
from sqlalchemy.engine import RowMapping

from core_platform.infrastructure.persistence.break_glass_schema import (
    break_glass_grant,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassRepository,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)


def _grant_from_row(
    row: RowMapping,
) -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=BreakGlassGrantId(
            row["id"]
        ),
        tenant_id=TenantId(
            row["tenant_id"]
        ),
        actor_id=ActorId(
            row["actor_id"]
        ),
        issued_by_actor_id=ActorId(
            row["issued_by_actor_id"]
        ),
        capabilities=tuple(
            row["capabilities"]
        ),
        scope=BreakGlassScope(
            kind=BreakGlassScopeKind(
                row["scope_kind"]
            ),
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
        ),
        reason=row["reason"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        status=BreakGlassGrantStatus(
            row["status"]
        ),
        accepted_acr_values=frozenset(
            row["accepted_acr_values"]
        ),
        required_amr=frozenset(
            row["required_amr"]
        ),
    )


class SqlBreakGlassRepository(
    BreakGlassRepository
):
    def __init__(
        self,
        database: Database,
    ) -> None:
        self._database = database

    async def list_candidate_grants(
        self,
        tenant_id: TenantId,
        actor_id: ActorId,
        capability: str,
        *,
        now: datetime,
    ) -> tuple[BreakGlassGrant, ...]:
        if (
            now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError(
                "now must be timezone-aware"
            )

        normalized_capability = capability.strip()

        if not normalized_capability:
            raise ValueError(
                "capability must not be empty"
            )

        statement = (
            select(break_glass_grant)
            .where(
                and_(
                    break_glass_grant.c.tenant_id
                    == tenant_id.value,
                    break_glass_grant.c.actor_id
                    == actor_id.value,
                    break_glass_grant.c.status
                    == "ACTIVE",
                    break_glass_grant.c.valid_from
                    <= now,
                    break_glass_grant.c.valid_until
                    > now,
                    any_(
                        break_glass_grant.c.capabilities
                    )
                    == normalized_capability,
                )
            )
            .order_by(
                break_glass_grant.c.valid_until.asc(),
                break_glass_grant.c.id.asc(),
            )
        )

        async with self._database.tenant_transaction(
            tenant_id.value
        ) as connection:
            rows = (
                (
                    await connection.execute(
                        statement
                    )
                )
                .mappings()
                .all()
            )

        return tuple(
            _grant_from_row(row)
            for row in rows
        )