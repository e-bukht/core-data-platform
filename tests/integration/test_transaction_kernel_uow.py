from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.idempotency import (
    IdempotencyAction,
    evaluate_idempotency,
)
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    IdempotencyRecordId,
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    IdempotencyRecord,
    IdempotencyStatus,
    MessageEnvelope,
    OutboxMessage,
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000401"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000402"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000403"))


def _run(coro: Coroutine[Any, Any, None]) -> None:
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
                        'transaction-kernel-test',
                        'Transaction Kernel Test',
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
                        'Transaction Kernel Test Actor'
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
                    CREATE TABLE transaction_test.probe (
                        id uuid PRIMARY KEY,
                        tenant_id uuid NOT NULL,
                        value varchar(100) NOT NULL
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE transaction_test.probe
                    ENABLE ROW LEVEL SECURITY
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE transaction_test.probe
                    FORCE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE POLICY probe_tenant_isolation
                    ON transaction_test.probe
                    USING (
                        tenant_id = platform.current_tenant_id()
                    )
                    WITH CHECK (
                        tenant_id = platform.current_tenant_id()
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
                    GRANT SELECT, INSERT
                    ON transaction_test.probe
                    TO coredata_runtime
                    """
                )
            )
    finally:
        engine.dispose()


def _context(
    suffix: int,
    *,
    operation: str = "transaction.test",
) -> TransactionContext:
    now = datetime.now(UTC)

    return TransactionContext(
        transaction_id=TransactionId(UUID(f"00000000-0000-7000-8000-{suffix:012d}")),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation=operation,
        capability="transaction.test.execute",
        started_at=now,
        idempotency_key=f"idem-{suffix}",
    )


def _idempotency(
    context: TransactionContext,
    suffix: int,
) -> IdempotencyRecord:
    now = datetime.now(UTC)

    return IdempotencyRecord(
        record_id=IdempotencyRecordId(UUID(f"00000000-0000-7001-8000-{suffix:012d}")),
        tenant_id=context.tenant_id,
        operation=context.operation,
        idempotency_key=f"idem-{suffix}",
        request_hash="sha256:" + ("a" * 64),
        status=IdempotencyStatus.IN_PROGRESS,
        transaction_id=context.transaction_id,
        result_reference=None,
        response_status=None,
        response_payload=None,
        created_at=now,
        completed_at=None,
        expires_at=now + timedelta(days=1),
    )


def _outbox(
    context: TransactionContext,
    suffix: int,
) -> OutboxMessage:
    now = datetime.now(UTC)

    return OutboxMessage(
        envelope=MessageEnvelope(
            message_id=MessageId(UUID(f"00000000-0000-7002-8000-{suffix:012d}")),
            message_type="transaction.test.created",
            schema_version=1,
            source="core-data-platform",
            tenant_id=context.tenant_id,
            transaction_id=context.transaction_id,
            actor_id=context.actor_id,
            occurred_at=now,
            correlation_id=context.correlation_id,
            causation_id=None,
            aggregate_type="TransactionProbe",
            aggregate_id=str(suffix),
            aggregate_version=1,
            payload={"suffix": suffix},
            payload_hash="sha256:" + ("b" * 64),
        ),
        available_at=now,
        published_at=None,
        attempt_count=0,
        lease_owner=None,
        lease_until=None,
        last_error=None,
    )


def _audit(
    context: TransactionContext,
    suffix: int,
) -> AuditRecord:
    return AuditRecord(
        record_id=AuditRecordId(UUID(f"00000000-0000-7003-8000-{suffix:012d}")),
        tenant_id=context.tenant_id,
        transaction_id=context.transaction_id,
        actor_id=context.actor_id,
        correlation_id=context.correlation_id,
        capability=context.capability,
        action=context.operation,
        resource_type="TransactionProbe",
        resource_id=str(suffix),
        outcome=AuditOutcome.SUCCESS,
        occurred_at=datetime.now(UTC),
        details={"suffix": suffix},
    )


async def _insert_atomic_set(
    uow: PostgresUnitOfWork,
    context: TransactionContext,
    suffix: int,
) -> None:
    connection = uow._require_connection()

    await connection.execute(
        text(
            """
            INSERT INTO transaction_test.probe (
                id,
                tenant_id,
                value
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                :value
            )
            """
        ),
        {
            "id": (f"00000000-0000-7004-8000-{suffix:012d}"),
            "tenant_id": str(context.tenant_id.value),
            "value": f"value-{suffix}",
        },
    )

    await uow.idempotency.add(_idempotency(context, suffix))
    outbox = _outbox(context, suffix)
    deferred_outbox = OutboxMessage(
        envelope=outbox.envelope,
        available_at=datetime.now(UTC) + timedelta(days=1),
        published_at=outbox.published_at,
        attempt_count=outbox.attempt_count,
        lease_owner=outbox.lease_owner,
        lease_until=outbox.lease_until,
        last_error=outbox.last_error,
    )
    await uow.outbox.add(deferred_outbox)
    await uow.audit.append(_audit(context, suffix))


async def _count(
    database: Database,
    table: str,
    suffix: int,
) -> int:
    ids = {
        "probe": (f"00000000-0000-7004-8000-{suffix:012d}"),
        "idempotency_record": (f"00000000-0000-7001-8000-{suffix:012d}"),
        "outbox_message": (f"00000000-0000-7002-8000-{suffix:012d}"),
        "audit_record": (f"00000000-0000-7003-8000-{suffix:012d}"),
    }

    qualified = "transaction_test.probe" if table == "probe" else f"platform.{table}"

    async with database.tenant_transaction(TENANT_ID.value) as connection:
        result = await connection.execute(
            text(
                f"""
                SELECT count(*)
                FROM {qualified}
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": ids[table]},
        )
        return int(result.scalar_one())


async def _exercise(runtime_url: str) -> None:
    database = Database(
        runtime_url,
        pool_size=2,
        max_overflow=0,
    )
    factory = PostgresUnitOfWorkFactory(database)

    try:
        # ----------------------------------------------------------
        # 1. Explicit commit + GUC propagation + atomic persistence
        # ----------------------------------------------------------

        committed = _context(501)

        uow = factory.create(committed)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            connection = active._require_connection()

            settings = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            current_setting(
                                'app.current_tenant_id'
                            ),
                            current_setting(
                                'app.current_actor_id'
                            ),
                            current_setting(
                                'app.current_correlation_id'
                            )
                        """
                    )
                )
            ).one()

            assert settings[0] == str(committed.tenant_id.value)
            assert settings[1] == str(committed.actor_id.value)
            assert settings[2] == str(committed.correlation_id.value)

            await _insert_atomic_set(
                active,
                committed,
                501,
            )
            await active.commit()

        for table in (
            "probe",
            "idempotency_record",
            "outbox_message",
            "audit_record",
        ):
            assert await _count(database, table, 501) == 1

        # ----------------------------------------------------------
        # 2. No explicit commit => rollback by default
        # ----------------------------------------------------------

        implicit_rollback = _context(502)

        uow = factory.create(implicit_rollback)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await _insert_atomic_set(
                active,
                implicit_rollback,
                502,
            )

        for table in (
            "probe",
            "idempotency_record",
            "outbox_message",
            "audit_record",
        ):
            assert await _count(database, table, 502) == 0

        # ----------------------------------------------------------
        # 3. Exception => rollback
        # ----------------------------------------------------------

        exception_rollback = _context(503)

        with pytest.raises(
            RuntimeError,
            match="expected test failure",
        ):
            uow = factory.create(exception_rollback)
            assert isinstance(uow, PostgresUnitOfWork)

            async with uow as active:
                await _insert_atomic_set(
                    active,
                    exception_rollback,
                    503,
                )
                raise RuntimeError("expected test failure")

        for table in (
            "probe",
            "idempotency_record",
            "outbox_message",
            "audit_record",
        ):
            assert await _count(database, table, 503) == 0

        # ----------------------------------------------------------
        # 4. Nested root UoW => fail fast
        # ----------------------------------------------------------

        outer_context = _context(504)
        inner_context = _context(505)

        outer = factory.create(outer_context)
        inner = factory.create(inner_context)

        assert isinstance(outer, PostgresUnitOfWork)
        assert isinstance(inner, PostgresUnitOfWork)

        async with outer:
            with pytest.raises(
                RuntimeError,
                match="Nested root UnitOfWork",
            ):
                async with inner:
                    raise AssertionError("nested UoW must not enter")

            await outer.rollback()

        # ----------------------------------------------------------
        # 5. Outbox fencing
        # ----------------------------------------------------------

        fence_context = _context(506)

        uow = factory.create(fence_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await active.outbox.add(_outbox(fence_context, 506))
            await active.commit()

        claim_context = _context(
            507,
            operation="outbox.dispatch",
        )
        uow = factory.create(claim_context)
        assert isinstance(uow, PostgresUnitOfWork)

        now = datetime.now(UTC)

        async with uow as active:
            claimed = await active.outbox.claim_ready(
                worker_id="worker-a",
                now=now,
                lease_until=now + timedelta(minutes=5),
                limit=10,
            )

            assert len(claimed) == 1
            assert (
                claimed[0].envelope.message_id
                == _outbox(
                    fence_context,
                    506,
                ).envelope.message_id
            )
            assert claimed[0].lease_owner == "worker-a"
            assert claimed[0].attempt_count == 1

            with pytest.raises(
                RuntimeError,
                match="Outbox lease ownership lost",
            ):
                await active.outbox.mark_published(
                    message_id=claimed[0].envelope.message_id,
                    worker_id="worker-stale",
                    expected_attempt=1,
                    published_at=datetime.now(UTC),
                )

            await active.outbox.mark_published(
                message_id=claimed[0].envelope.message_id,
                worker_id="worker-a",
                expected_attempt=1,
                published_at=datetime.now(UTC),
            )

            await active.commit()

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
def test_transaction_kernel_unit_of_work(
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


def _concurrent_context(
    suffix: int,
    *,
    operation: str,
    idempotency_key: str,
) -> TransactionContext:
    base = _context(
        suffix,
        operation=operation,
    )

    return TransactionContext(
        transaction_id=base.transaction_id,
        tenant_id=base.tenant_id,
        actor_id=base.actor_id,
        correlation_id=base.correlation_id,
        operation=operation,
        capability=base.capability,
        started_at=base.started_at,
        idempotency_key=idempotency_key,
    )


def _idempotency_for_key(
    context: TransactionContext,
    *,
    record_suffix: int,
    idempotency_key: str,
    request_hash: str,
) -> IdempotencyRecord:
    now = datetime.now(UTC)

    return IdempotencyRecord(
        record_id=IdempotencyRecordId(UUID(f"00000000-0000-7010-8000-{record_suffix:012d}")),
        tenant_id=context.tenant_id,
        operation=context.operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status=IdempotencyStatus.IN_PROGRESS,
        transaction_id=context.transaction_id,
        result_reference=None,
        response_status=None,
        response_payload=None,
        created_at=now,
        completed_at=None,
        expires_at=now + timedelta(days=1),
    )


async def _insert_concurrency_probe(
    uow: PostgresUnitOfWork,
    *,
    suffix: int,
    value: str,
) -> None:
    connection = uow._require_connection()

    await connection.execute(
        text(
            """
            INSERT INTO transaction_test.probe (
                id,
                tenant_id,
                value
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                :value
            )
            """
        ),
        {
            "id": (f"00000000-0000-7011-8000-{suffix:012d}"),
            "tenant_id": str(TENANT_ID.value),
            "value": value,
        },
    )


async def _probe_count_by_prefix(
    database: Database,
    prefix: str,
) -> int:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        result = await connection.execute(
            text(
                """
                SELECT count(*)
                FROM transaction_test.probe
                WHERE value LIKE :pattern
                """
            ),
            {"pattern": f"{prefix}%"},
        )

        return int(result.scalar_one())


async def _exercise_concurrency(
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
        # 1. Same idempotency key, concurrent requests:
        #    one commit, one unique-key loser, then replay.
        # ----------------------------------------------------------

        operation = "transaction.concurrent"
        idempotency_key = "same-key"
        request_hash = "sha256:" + ("c" * 64)
        barrier = asyncio.Barrier(2)

        async def contender(
            suffix: int,
        ) -> str:
            context = _concurrent_context(
                suffix,
                operation=operation,
                idempotency_key=idempotency_key,
            )

            uow = factory.create(context)
            assert isinstance(
                uow,
                PostgresUnitOfWork,
            )

            try:
                async with uow as active:
                    existing = await active.idempotency.get(
                        operation=operation,
                        idempotency_key=idempotency_key,
                    )

                    decision = evaluate_idempotency(
                        existing=existing,
                        operation=operation,
                        request_hash=request_hash,
                    )

                    assert decision.action is IdempotencyAction.EXECUTE

                    await barrier.wait()

                    await active.idempotency.add(
                        _idempotency_for_key(
                            context,
                            record_suffix=suffix,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                        )
                    )

                    await _insert_concurrency_probe(
                        active,
                        suffix=suffix,
                        value=(f"idempotency-race-{suffix}"),
                    )

                    completed = await active.idempotency.complete(
                        operation=operation,
                        idempotency_key=idempotency_key,
                        result_reference=(f"result-{suffix}"),
                        response_status=200,
                        response_payload={"suffix": suffix},
                        completed_at=datetime.now(UTC),
                    )

                    assert completed.status is IdempotencyStatus.COMPLETED

                    await active.commit()

                    return "EXECUTE"

            except IntegrityError:
                return "UNIQUE_CONFLICT"

        outcomes = await asyncio.gather(
            contender(601),
            contender(602),
        )

        assert sorted(outcomes) == [
            "EXECUTE",
            "UNIQUE_CONFLICT",
        ]

        assert (
            await _probe_count_by_prefix(
                database,
                "idempotency-race-",
            )
            == 1
        )

        replay_context = _concurrent_context(
            603,
            operation=operation,
            idempotency_key=idempotency_key,
        )

        replay_uow = factory.create(replay_context)
        assert isinstance(
            replay_uow,
            PostgresUnitOfWork,
        )

        async with replay_uow as active:
            existing = await active.idempotency.get(
                operation=operation,
                idempotency_key=idempotency_key,
            )

            replay = evaluate_idempotency(
                existing=existing,
                operation=operation,
                request_hash=request_hash,
            )

            assert replay.action is IdempotencyAction.REPLAY
            assert replay.record is not None
            assert replay.record.status is IdempotencyStatus.COMPLETED

        # ----------------------------------------------------------
        # 2. Rollback before commit must not strand the key.
        # ----------------------------------------------------------

        retry_operation = "transaction.retry"
        retry_key = "rollback-retry-key"
        retry_hash = "sha256:" + ("d" * 64)

        rollback_context = _concurrent_context(
            611,
            operation=retry_operation,
            idempotency_key=retry_key,
        )

        rollback_uow = factory.create(rollback_context)
        assert isinstance(
            rollback_uow,
            PostgresUnitOfWork,
        )

        async with rollback_uow as active:
            await active.idempotency.add(
                _idempotency_for_key(
                    rollback_context,
                    record_suffix=611,
                    idempotency_key=retry_key,
                    request_hash=retry_hash,
                )
            )

            await _insert_concurrency_probe(
                active,
                suffix=611,
                value="rollback-retry-aborted",
            )

            # No commit: __aexit__ must rollback.

        retry_context = _concurrent_context(
            612,
            operation=retry_operation,
            idempotency_key=retry_key,
        )

        retry_uow = factory.create(retry_context)
        assert isinstance(
            retry_uow,
            PostgresUnitOfWork,
        )

        async with retry_uow as active:
            existing = await active.idempotency.get(
                operation=retry_operation,
                idempotency_key=retry_key,
            )

            assert existing is None

            await active.idempotency.add(
                _idempotency_for_key(
                    retry_context,
                    record_suffix=612,
                    idempotency_key=retry_key,
                    request_hash=retry_hash,
                )
            )

            await _insert_concurrency_probe(
                active,
                suffix=612,
                value="rollback-retry-committed",
            )

            await active.idempotency.complete(
                operation=retry_operation,
                idempotency_key=retry_key,
                result_reference="retry-result",
                response_status=200,
                response_payload={"retried": True},
                completed_at=datetime.now(UTC),
            )

            await active.commit()

        assert (
            await _probe_count_by_prefix(
                database,
                "rollback-retry-",
            )
            == 1
        )

        # ----------------------------------------------------------
        # 3. Two concurrent dispatchers must claim distinct rows.
        # ----------------------------------------------------------

        for suffix in (621, 622):
            context = _context(
                suffix,
                operation="outbox.seed",
            )
            seed_uow = factory.create(context)

            assert isinstance(
                seed_uow,
                PostgresUnitOfWork,
            )

            async with seed_uow as active:
                await active.outbox.add(_outbox(context, suffix))
                await active.commit()

        dispatch_barrier = asyncio.Barrier(2)
        dispatch_now = datetime.now(UTC)

        async def dispatcher(
            suffix: int,
            worker_id: str,
        ) -> OutboxMessage:
            context = _context(
                suffix,
                operation="outbox.dispatch",
            )

            uow = factory.create(context)
            assert isinstance(
                uow,
                PostgresUnitOfWork,
            )

            async with uow as active:
                await dispatch_barrier.wait()

                claimed = await active.outbox.claim_ready(
                    worker_id=worker_id,
                    now=dispatch_now,
                    lease_until=(dispatch_now + timedelta(minutes=5)),
                    limit=1,
                )

                assert len(claimed) == 1
                assert claimed[0].lease_owner == worker_id
                assert claimed[0].attempt_count == 1

                await active.commit()

                return claimed[0]

        first, second = await asyncio.gather(
            dispatcher(623, "worker-a"),
            dispatcher(624, "worker-b"),
        )

        assert first.envelope.message_id != second.envelope.message_id

        assert {
            first.envelope.message_id,
            second.envelope.message_id,
        } == {
            _outbox(
                _context(
                    621,
                    operation="outbox.seed",
                ),
                621,
            ).envelope.message_id,
            _outbox(
                _context(
                    622,
                    operation="outbox.seed",
                ),
                622,
            ).envelope.message_id,
        }

        # ----------------------------------------------------------
        # 4. Publish failure -> release -> same message retry,
        #    with a new attempt number.
        # ----------------------------------------------------------

        released = first
        release_worker = released.lease_owner
        assert release_worker is not None

        release_context = _context(
            625,
            operation="outbox.dispatch",
        )

        release_uow = factory.create(release_context)
        assert isinstance(
            release_uow,
            PostgresUnitOfWork,
        )

        retry_at = datetime.now(UTC)

        async with release_uow as active:
            await active.outbox.release(
                message_id=(released.envelope.message_id),
                worker_id=release_worker,
                expected_attempt=1,
                available_at=retry_at,
                error="publisher unavailable",
            )

            await active.commit()

        reclaim_context = _context(
            626,
            operation="outbox.dispatch",
        )
        reclaim_uow = factory.create(reclaim_context)

        assert isinstance(
            reclaim_uow,
            PostgresUnitOfWork,
        )

        async with reclaim_uow as active:
            reclaimed = await active.outbox.claim_ready(
                worker_id="worker-retry",
                now=(retry_at + timedelta(seconds=1)),
                lease_until=(retry_at + timedelta(minutes=5)),
                limit=1,
            )

            assert len(reclaimed) == 1
            assert reclaimed[0].envelope.message_id == released.envelope.message_id
            assert reclaimed[0].attempt_count == 2
            assert reclaimed[0].lease_owner == "worker-retry"
            assert reclaimed[0].last_error is None

            await active.commit()

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
def test_transaction_kernel_concurrency(
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

        _run(_exercise_concurrency(runtime_url))
