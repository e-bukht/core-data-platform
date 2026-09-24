from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import AuditRecordId, TransactionId
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = TenantId(UUID("00000000-0000-7200-8000-000000001201"))
ACTOR_ID = ActorId(UUID("00000000-0000-7200-8000-000000001202"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7200-8000-000000001203"))

OCCURRED_AT = datetime(
    2026,
    9,
    24,
    10,
    30,
    tzinfo=UTC,
)


def _run(
    coro: Coroutine[Any, Any, None],
) -> None:
    def loop_factory() -> asyncio.AbstractEventLoop:
        return asyncio.SelectorEventLoop(selectors.SelectSelector())

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(coro)


def _seed(migration_url: str) -> None:
    engine = create_engine(migration_url)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO platform.tenant (
                        id,
                        code,
                        display_name,
                        status
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        'audit-test-tenant',
                        'Audit Test Tenant',
                        'ACTIVE'
                    )
                    """
                ),
                {"tenant_id": str(TENANT_ID.value)},
            )

            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor (
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'SERVICE',
                        'ACTIVE',
                        'Audit Test Actor'
                    )
                    """
                ),
                {"actor_id": str(ACTOR_ID.value)},
            )
    finally:
        engine.dispose()


def _context(
    suffix: int,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(UUID(f"00000000-0000-7201-8000-{suffix:012d}")),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="order.confirm",
        capability="order.confirm",
        started_at=OCCURRED_AT,
    )


def _audit(
    context: TransactionContext,
    suffix: int,
) -> AuditRecord:
    details: dict[str, object] = {
        "suffix": suffix,
        "channel": "integration-test",
    }

    return AuditRecord(
        record_id=AuditRecordId(UUID(f"00000000-0000-7202-8000-{suffix:012d}")),
        tenant_id=context.tenant_id,
        transaction_id=context.transaction_id,
        actor_id=context.actor_id,
        correlation_id=context.correlation_id,
        capability=context.capability,
        action=context.operation,
        resource_type="Order",
        resource_id=f"ORD-{suffix}",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=OCCURRED_AT,
        details=details,
    )


async def _assert_persisted(
    database: Database,
    *,
    record: AuditRecord,
) -> None:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT
                        id,
                        tenant_id,
                        transaction_id,
                        actor_id,
                        correlation_id,
                        capability,
                        action,
                        resource_type,
                        resource_id,
                        outcome,
                        occurred_at,
                        details
                    FROM platform.audit_record
                    WHERE id = CAST(:id AS uuid)
                    """
                    ),
                    {"id": str(record.record_id.value)},
                )
            )
            .mappings()
            .one()
        )

    assert row["id"] == record.record_id.value
    assert row["tenant_id"] == record.tenant_id.value
    assert row["transaction_id"] == record.transaction_id.value
    assert row["actor_id"] == record.actor_id.value
    assert row["correlation_id"] == record.correlation_id.value
    assert row["capability"] == record.capability
    assert row["action"] == record.action
    assert row["resource_type"] == record.resource_type
    assert row["resource_id"] == record.resource_id
    assert row["outcome"] == record.outcome.value
    assert row["occurred_at"] == record.occurred_at
    assert row["details"] == dict(record.details)


async def _count(
    database: Database,
    record_id: AuditRecordId,
) -> int:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        value = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.audit_record
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": str(record_id.value)},
        )

    return int(value or 0)


async def _exercise(
    runtime_url: str,
) -> None:
    database = Database(
        runtime_url,
        pool_size=2,
        max_overflow=0,
    )
    factory = PostgresUnitOfWorkFactory(database)

    try:
        # ------------------------------------------------------
        # 1. Durable commit + exact correlation persistence.
        # ------------------------------------------------------

        committed_context = _context(1201)
        committed_record = _audit(
            committed_context,
            1201,
        )

        uow = factory.create(committed_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await active.audit.append(committed_record)
            await active.commit()

        assert (
            await _count(
                database,
                committed_record.record_id,
            )
            == 1
        )

        await _assert_persisted(
            database,
            record=committed_record,
        )

        # ------------------------------------------------------
        # 2. Audit participates in the UoW rollback.
        # ------------------------------------------------------

        rollback_context = _context(1202)
        rollback_record = _audit(
            rollback_context,
            1202,
        )

        uow = factory.create(rollback_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await active.audit.append(rollback_record)
            # No explicit commit => rollback.

        assert (
            await _count(
                database,
                rollback_record.record_id,
            )
            == 0
        )

        # ------------------------------------------------------
        # 3. Trusted correlation fields cannot diverge from UoW.
        # ------------------------------------------------------

        guarded_context = _context(1203)
        base_record = _audit(
            guarded_context,
            1203,
        )

        uow = factory.create(guarded_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            with pytest.raises(
                ValueError,
                match="Audit tenant does not match UnitOfWork",
            ):
                await active.audit.append(
                    replace(
                        base_record,
                        tenant_id=TenantId(UUID("00000000-0000-7200-8000-000000009901")),
                    )
                )

            with pytest.raises(
                ValueError,
                match=("Audit transaction does not match UnitOfWork"),
            ):
                await active.audit.append(
                    replace(
                        base_record,
                        transaction_id=TransactionId(UUID("00000000-0000-7201-8000-000000009902")),
                    )
                )

            with pytest.raises(
                ValueError,
                match="Audit actor does not match UnitOfWork",
            ):
                await active.audit.append(
                    replace(
                        base_record,
                        actor_id=ActorId(UUID("00000000-0000-7200-8000-000000009903")),
                    )
                )

            with pytest.raises(
                ValueError,
                match=("Audit correlation does not match UnitOfWork"),
            ):
                await active.audit.append(
                    replace(
                        base_record,
                        correlation_id=CorrelationId(UUID("00000000-0000-7200-8000-000000009904")),
                    )
                )

            await active.rollback()

        assert (
            await _count(
                database,
                base_record.record_id,
            )
            == 0
        )

    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_durable_audit_is_atomic_and_correlated(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        admin_database_url = admin_url(postgres)

        migration_url, runtime_url = provision_roles(admin_database_url)

        run_alembic(
            migration_url,
            runtime_url,
        )

        _seed(migration_url)

        _run(_exercise(runtime_url))
