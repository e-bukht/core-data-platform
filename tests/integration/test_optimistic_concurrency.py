from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from testcontainers.community.postgres import PostgresContainer

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.optimistic_concurrency import (
    compare_and_swap,
)
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.errors import (
    ConcurrencyConflict,
)
from core_platform.transaction_kernel.ids import TransactionId
from core_platform.transaction_kernel.models import (
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_A = TenantId(UUID("00000000-0000-7000-8000-000000000701"))
TENANT_B = TenantId(UUID("00000000-0000-7000-8000-000000000702"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000703"))
RESOURCE_ID = UUID("00000000-0000-7000-8000-000000000704")
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000705"))

metadata = MetaData(schema="transaction_test")

versioned_probe = Table(
    "versioned_probe",
    metadata,
    Column(
        "id",
        SqlUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        nullable=False,
    ),
    Column(
        "value",
        String(100),
        nullable=False,
    ),
    Column(
        "version",
        BigInteger(),
        nullable=False,
    ),
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
                    VALUES
                    (
                        CAST(:tenant_a AS uuid),
                        'cas-tenant-a',
                        'CAS Tenant A',
                        'ACTIVE'
                    ),
                    (
                        CAST(:tenant_b AS uuid),
                        'cas-tenant-b',
                        'CAS Tenant B',
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_a": str(TENANT_A.value),
                    "tenant_b": str(TENANT_B.value),
                },
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
                        'CAS Test Actor'
                    )
                    """
                ),
                {"actor_id": str(ACTOR_ID.value)},
            )

            connection.execute(
                text(
                    """
                    CREATE SCHEMA transaction_test
                    AUTHORIZATION coredata_migrator
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE TABLE
                    transaction_test.versioned_probe (
                        id uuid PRIMARY KEY,
                        tenant_id uuid NOT NULL,
                        value varchar(100) NOT NULL,
                        version bigint NOT NULL
                            CHECK (version >= 0)
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE
                    transaction_test.versioned_probe
                    ENABLE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE
                    transaction_test.versioned_probe
                    FORCE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE POLICY
                    versioned_probe_tenant_isolation
                    ON transaction_test.versioned_probe
                    USING (
                        tenant_id =
                        platform.current_tenant_id()
                    )
                    WITH CHECK (
                        tenant_id =
                        platform.current_tenant_id()
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    GRANT USAGE
                    ON SCHEMA transaction_test
                    TO coredata_runtime
                    """
                )
            )

            connection.execute(
                text(
                    """
                    GRANT SELECT, INSERT, UPDATE
                    ON transaction_test.versioned_probe
                    TO coredata_runtime
                    """
                )
            )
    finally:
        engine.dispose()


def _context(
    *,
    tenant_id: TenantId,
    suffix: int,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(UUID(f"00000000-0000-7010-8000-{suffix:012d}")),
        tenant_id=tenant_id,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="cas.test",
        capability="cas.test.write",
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )


async def _exercise(
    runtime_url: str,
) -> None:
    database = Database(
        runtime_url,
        pool_size=4,
        max_overflow=0,
    )
    factory = PostgresUnitOfWorkFactory(database)

    try:
        # ----------------------------------------------------------
        # Seed version 0 through the runtime role + RLS.
        # ----------------------------------------------------------

        seed_uow = factory.create(
            _context(
                tenant_id=TENANT_A,
                suffix=701,
            )
        )
        assert isinstance(
            seed_uow,
            PostgresUnitOfWork,
        )

        async with seed_uow as active:
            connection = active._require_connection()

            await connection.execute(
                versioned_probe.insert().values(
                    id=RESOURCE_ID,
                    tenant_id=TENANT_A.value,
                    value="initial",
                    version=0,
                )
            )

            await active.commit()

        # ----------------------------------------------------------
        # Two writers both observe version 0.
        # Exactly one CAS may commit.
        # ----------------------------------------------------------

        barrier = asyncio.Barrier(2)

        async def writer(
            *,
            suffix: int,
            value: str,
        ) -> tuple[
            str,
            str,
            int | None,
            ConcurrencyConflict | None,
        ]:
            uow = factory.create(
                _context(
                    tenant_id=TENANT_A,
                    suffix=suffix,
                )
            )
            assert isinstance(
                uow,
                PostgresUnitOfWork,
            )

            try:
                async with uow as active:
                    connection = active._require_connection()

                    observed_version = (
                        await connection.execute(
                            select(versioned_probe.c.version).where(
                                versioned_probe.c.id == RESOURCE_ID
                            )
                        )
                    ).scalar_one()

                    assert observed_version == 0

                    await barrier.wait()

                    new_version = await compare_and_swap(
                        connection,
                        table=versioned_probe,
                        tenant_id=TENANT_A.value,
                        resource_id=RESOURCE_ID,
                        resource_type=("VersionedProbe"),
                        expected_version=(observed_version),
                        values={
                            "value": value,
                        },
                    )

                    await active.commit()

                    return (
                        "SUCCESS",
                        value,
                        new_version,
                        None,
                    )

            except ConcurrencyConflict as conflict:
                return (
                    "CONFLICT",
                    value,
                    None,
                    conflict,
                )

        first, second = await asyncio.gather(
            writer(
                suffix=711,
                value="writer-a",
            ),
            writer(
                suffix=712,
                value="writer-b",
            ),
        )

        outcomes = (first, second)

        successes = [result for result in outcomes if result[0] == "SUCCESS"]
        conflicts = [result for result in outcomes if result[0] == "CONFLICT"]

        assert len(successes) == 1
        assert len(conflicts) == 1

        winner = successes[0]

        assert winner[2] == 1

        stale_conflict = conflicts[0][3]
        assert stale_conflict is not None
        assert stale_conflict.expected_version == 0
        assert str(stale_conflict) == "Optimistic concurrency conflict"
        assert not hasattr(
            stale_conflict,
            "actual_version",
        )

        # ----------------------------------------------------------
        # Winner's state must be intact at version 1.
        # ----------------------------------------------------------

        async with database.tenant_transaction(TENANT_A.value) as connection:
            row = (
                await connection.execute(
                    select(
                        versioned_probe.c.value,
                        versioned_probe.c.version,
                    ).where(versioned_probe.c.id == RESOURCE_ID)
                )
            ).one()

        assert row.value == winner[1]
        assert row.version == 1

        # ----------------------------------------------------------
        # Deterministic stale write after commit.
        # ----------------------------------------------------------

        stale_uow = factory.create(
            _context(
                tenant_id=TENANT_A,
                suffix=713,
            )
        )
        assert isinstance(
            stale_uow,
            PostgresUnitOfWork,
        )

        with pytest.raises(
            ConcurrencyConflict,
            match="Optimistic concurrency conflict",
        ) as stale:
            async with stale_uow as active:
                await compare_and_swap(
                    active._require_connection(),
                    table=versioned_probe,
                    tenant_id=TENANT_A.value,
                    resource_id=RESOURCE_ID,
                    resource_type="VersionedProbe",
                    expected_version=0,
                    values={
                        "value": "stale-overwrite",
                    },
                )

        assert stale.value.expected_version == 0
        assert not hasattr(
            stale.value,
            "actual_version",
        )

        # ----------------------------------------------------------
        # Cross-tenant attempt:
        # indistinguishable from stale/missing resource.
        # ----------------------------------------------------------

        cross_tenant_uow = factory.create(
            _context(
                tenant_id=TENANT_B,
                suffix=714,
            )
        )
        assert isinstance(
            cross_tenant_uow,
            PostgresUnitOfWork,
        )

        with pytest.raises(
            ConcurrencyConflict,
            match="Optimistic concurrency conflict",
        ) as cross_tenant:
            async with cross_tenant_uow as active:
                await compare_and_swap(
                    active._require_connection(),
                    table=versioned_probe,
                    tenant_id=TENANT_B.value,
                    resource_id=RESOURCE_ID,
                    resource_type="VersionedProbe",
                    expected_version=1,
                    values={
                        "value": "cross-tenant",
                    },
                )

        assert cross_tenant.value.resource_id == str(RESOURCE_ID)
        assert cross_tenant.value.expected_version == 1
        assert not hasattr(
            cross_tenant.value,
            "actual_version",
        )

        # ----------------------------------------------------------
        # Cross-tenant/stale attempts changed nothing.
        # ----------------------------------------------------------

        async with database.tenant_transaction(TENANT_A.value) as connection:
            final_row = (
                await connection.execute(
                    select(
                        versioned_probe.c.value,
                        versioned_probe.c.version,
                    ).where(versioned_probe.c.id == RESOURCE_ID)
                )
            ).one()

        assert final_row.value == winner[1]
        assert final_row.version == 1

        async with database.tenant_transaction(TENANT_B.value) as connection:
            invisible_count = (
                await connection.execute(
                    select(versioned_probe.c.id).where(versioned_probe.c.id == RESOURCE_ID)
                )
            ).all()

        assert invisible_count == []

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
def test_optimistic_concurrency_cas(
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
