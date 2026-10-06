from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from core_platform.foundation.errors import BusinessRuleViolation
from core_platform.infrastructure.persistence.break_glass_schema import (
    break_glass_grant,
)
from core_platform.infrastructure.persistence.optimistic_concurrency import (
    compare_and_swap,
)
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
)
from core_platform.platform_kernel.break_glass.lifecycle import (
    require_break_glass_status_transition,
)
from core_platform.platform_kernel.ids import (
    BreakGlassGrantId,
)
from core_platform.transaction_kernel.errors import (
    ConcurrencyConflict,
)
from core_platform.transaction_kernel.models import (
    TransactionContext,
)

ConnectionProvider = Callable[[], AsyncConnection]

_BREAK_GLASS_RESOURCE_TYPE = "BreakGlassGrant"


class PostgresBreakGlassLifecycleStore:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def issue(
        self,
        *,
        grant: BreakGlassGrant,
        issued_at: datetime,
    ) -> int:
        if (
            issued_at.tzinfo is None
            or issued_at.utcoffset() is None
        ):
            raise ValueError(
                "issued_at must be timezone-aware"
            )

        if grant.tenant_id != self._context.tenant_id:
            raise ValueError(
                "Break-glass grant tenant "
                "does not match UnitOfWork"
            )

        if grant.issued_by_actor_id != self._context.actor_id:
            raise ValueError(
                "Break-glass grant issuer "
                "does not match UnitOfWork actor"
            )

        if grant.status is not BreakGlassGrantStatus.ACTIVE:
            raise ValueError(
                "New break-glass grant must be ACTIVE"
            )

        statement = (
            insert(break_glass_grant)
            .values(
                id=grant.grant_id.value,
                tenant_id=grant.tenant_id.value,
                actor_id=grant.actor_id.value,
                issued_by_actor_id=(
                    grant.issued_by_actor_id.value
                ),
                capabilities=list(
                    grant.capabilities
                ),
                scope_kind=grant.scope.kind.value,
                resource_type=(
                    grant.scope.resource_type
                ),
                resource_id=(
                    grant.scope.resource_id
                ),
                reason=grant.reason,
                valid_from=grant.valid_from,
                valid_until=grant.valid_until,
                status=grant.status.value,
                accepted_acr_values=list(
                    sorted(
                        grant.accepted_acr_values
                    )
                ),
                required_amr=list(
                    sorted(
                        grant.required_amr
                    )
                ),
                version=0,
                created_at=issued_at,
                updated_at=issued_at,
            )
            .returning(
                break_glass_grant.c.version
            )
        )

        version = (
            await self._connection().execute(
                statement
            )
        ).scalar_one()

        return int(version)

    async def transition_status(
        self,
        *,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        expected_current_status: BreakGlassGrantStatus,
        target_status: BreakGlassGrantStatus,
        changed_at: datetime,
    ) -> int:
        if expected_version < 0:
            raise ValueError(
                "expected_version must be >= 0"
            )

        if (
            changed_at.tzinfo is None
            or changed_at.utcoffset() is None
        ):
            raise ValueError(
                "changed_at must be timezone-aware"
            )

        connection = self._connection()

        statement = select(
            break_glass_grant.c.status,
            break_glass_grant.c.valid_from,
            break_glass_grant.c.valid_until,
        ).where(
            break_glass_grant.c.tenant_id
            == self._context.tenant_id.value,
            break_glass_grant.c.id
            == grant_id.value,
            break_glass_grant.c.version
            == expected_version,
        )

        current = (
            await connection.execute(statement)
        ).one_or_none()

        if current is None:
            raise ConcurrencyConflict(
                resource_type=_BREAK_GLASS_RESOURCE_TYPE,
                resource_id=str(grant_id.value),
                expected_version=expected_version,
            )

        current_status = BreakGlassGrantStatus(
            current.status
        )

        if current_status is not expected_current_status:
            raise ConcurrencyConflict(
                resource_type=_BREAK_GLASS_RESOURCE_TYPE,
                resource_id=str(grant_id.value),
                expected_version=expected_version,
            )

        if (
            target_status is BreakGlassGrantStatus.ACTIVE
            and not (
                current.valid_from
                <= changed_at
                < current.valid_until
            )
        ):
            raise BusinessRuleViolation(
                "BREAK_GLASS.RESUME.OUTSIDE_VALIDITY_WINDOW",
                (
                    "Break-glass grant cannot be resumed "
                    "outside its validity window"
                ),
                correlation_id=str(
                    self._context.correlation_id
                ),
            )

        require_break_glass_status_transition(
            current_status,
            target_status,
        )

        return await compare_and_swap(
            connection,
            table=break_glass_grant,
            tenant_id=self._context.tenant_id.value,
            resource_id=grant_id.value,
            resource_type=_BREAK_GLASS_RESOURCE_TYPE,
            expected_version=expected_version,
            values={
                "status": target_status.value,
                "updated_at": changed_at,
            },
        )
