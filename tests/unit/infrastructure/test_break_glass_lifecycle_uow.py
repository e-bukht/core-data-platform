from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.break_glass_lifecycle_store import (
    PostgresBreakGlassLifecycleStore,
)
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import TransactionId
from core_platform.transaction_kernel.models import TransactionContext


class _Database:
    pass


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(
            UUID("00000000-0000-7000-8000-000000000010")
        ),
        tenant_id=TenantId(
            UUID("00000000-0000-7000-8000-000000000011")
        ),
        actor_id=ActorId(
            UUID("00000000-0000-7000-8000-000000000012")
        ),
        correlation_id=CorrelationId(
            UUID("00000000-0000-7000-8000-000000000013")
        ),
        operation="security.break-glass.suspend",
        capability="platform.break-glass.manage",
        started_at=datetime(
            2026,
            10,
            5,
            17,
            30,
            tzinfo=UTC,
        ),
        idempotency_key=None,
    )


def test_postgres_uow_exposes_break_glass_lifecycle_store() -> None:
    uow = PostgresUnitOfWork(
        _Database(),  # type: ignore[arg-type]
        _context(),
    )

    assert isinstance(
        uow.break_glass_lifecycle,
        PostgresBreakGlassLifecycleStore,
    )
