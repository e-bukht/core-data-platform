from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from datetime import UTC, datetime
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
from core_platform.transaction_kernel.errors import (
    InboxMessageConflictError,
)
from core_platform.transaction_kernel.ids import (
    InboxRecordId,
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.inbox import (
    InboxAction,
    evaluate_inbox,
)
from core_platform.transaction_kernel.models import (
    InboxMessage,
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000901"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000902"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000903"))

CONSUMER_NAME = "transaction-test-consumer"

MESSAGE_ONE = MessageId(UUID("00000000-0000-7000-8000-000000000911"))
MESSAGE_RETRY = MessageId(UUID("00000000-0000-7000-8000-000000000912"))

PAYLOAD_HASH_ONE = "sha256:" + ("a" * 64)
PAYLOAD_HASH_RETRY = "sha256:" + ("b" * 64)


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
                        'inbox-test-tenant',
                        'Inbox Test Tenant',
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
                        'Inbox Test Actor'
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
                    transaction_test.inbox_effect (
                        id uuid PRIMARY KEY,
                        tenant_id uuid NOT NULL,
                        message_id uuid NOT NULL,
                        effect_value varchar(100)
                            NOT NULL
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE
                    transaction_test.inbox_effect
                    ENABLE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE
                    transaction_test.inbox_effect
                    FORCE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE POLICY
                    inbox_effect_tenant_isolation
                    ON transaction_test.inbox_effect
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
                    GRANT SELECT, INSERT
                    ON transaction_test.inbox_effect
                    TO coredata_runtime
                    """
                )
            )
    finally:
        engine.dispose()


def _context(
    suffix: int,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(UUID(f"00000000-0000-7020-8000-{suffix:012d}")),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="inbox.consume",
        capability="inbox.consume",
        started_at=datetime.now(UTC),
    )


def _inbox_message(
    *,
    context: TransactionContext,
    message_id: MessageId,
    payload_hash: str,
    suffix: int,
) -> InboxMessage:
    return InboxMessage(
        record_id=InboxRecordId(UUID(f"00000000-0000-7021-8000-{suffix:012d}")),
        tenant_id=context.tenant_id,
        consumer_name=CONSUMER_NAME,
        message_id=message_id,
        message_type="transaction.test.received",
        correlation_id=context.correlation_id,
        causation_id=None,
        payload_hash=payload_hash,
        received_at=datetime.now(UTC),
        processed_at=None,
    )


async def _insert_effect(
    uow: PostgresUnitOfWork,
    *,
    message_id: MessageId,
    suffix: int,
) -> None:
    connection = uow._require_connection()

    await connection.execute(
        text(
            """
            INSERT INTO transaction_test.inbox_effect (
                id,
                tenant_id,
                message_id,
                effect_value
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:message_id AS uuid),
                :effect_value
            )
            """
        ),
        {
            "id": (f"00000000-0000-7022-8000-{suffix:012d}"),
            "tenant_id": str(TENANT_ID.value),
            "message_id": str(message_id.value),
            "effect_value": f"effect-{suffix}",
        },
    )


async def _effect_count(
    database: Database,
    *,
    message_id: MessageId,
) -> int:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        result = await connection.execute(
            text(
                """
                SELECT count(*)
                FROM transaction_test.inbox_effect
                WHERE message_id =
                    CAST(:message_id AS uuid)
                """
            ),
            {"message_id": str(message_id.value)},
        )

        return int(result.scalar_one())


async def _stored_inbox(
    factory: PostgresUnitOfWorkFactory,
    *,
    message_id: MessageId,
    suffix: int,
) -> InboxMessage | None:
    uow = factory.create(_context(suffix))

    assert isinstance(
        uow,
        PostgresUnitOfWork,
    )

    async with uow as active:
        return await active.inbox.get(
            consumer_name=CONSUMER_NAME,
            message_id=message_id,
        )


async def _consume(
    factory: PostgresUnitOfWorkFactory,
    *,
    message_id: MessageId,
    payload_hash: str,
    suffix: int,
    fail_handler: bool = False,
    race_barrier: asyncio.Barrier | None = None,
) -> InboxAction:
    context = _context(suffix)

    uow = factory.create(context)
    assert isinstance(
        uow,
        PostgresUnitOfWork,
    )

    async with uow as active:
        existing = await active.inbox.get(
            consumer_name=CONSUMER_NAME,
            message_id=message_id,
        )

        if race_barrier is not None:
            await race_barrier.wait()

        decision = evaluate_inbox(
            existing=existing,
            consumer_name=CONSUMER_NAME,
            message_id=message_id,
            payload_hash=payload_hash,
        )

        if decision.action is InboxAction.DUPLICATE:
            return decision.action

        if decision.action is InboxAction.IN_PROGRESS:
            return decision.action

        message = _inbox_message(
            context=context,
            message_id=message_id,
            payload_hash=payload_hash,
            suffix=suffix,
        )

        await active.inbox.add(message)

        await _insert_effect(
            active,
            message_id=message_id,
            suffix=suffix,
        )

        if fail_handler:
            raise RuntimeError("simulated handler failure")

        await active.inbox.mark_processed(
            consumer_name=CONSUMER_NAME,
            message_id=message_id,
            processed_at=datetime.now(UTC),
        )

        await active.commit()

        return InboxAction.PROCESS


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
        # C-I3-13:
        # first delivery produces exactly one business effect.
        # ----------------------------------------------------------

        action = await _consume(
            factory,
            message_id=MESSAGE_ONE,
            payload_hash=PAYLOAD_HASH_ONE,
            suffix=901,
        )

        assert action is InboxAction.PROCESS

        assert (
            await _effect_count(
                database,
                message_id=MESSAGE_ONE,
            )
            == 1
        )

        stored = await _stored_inbox(
            factory,
            message_id=MESSAGE_ONE,
            suffix=902,
        )

        assert stored is not None
        assert stored.processed_at is not None
        assert stored.payload_hash == PAYLOAD_HASH_ONE

        # ----------------------------------------------------------
        # C-I3-14:
        # same message + same payload is duplicate;
        # no second business effect.
        # ----------------------------------------------------------

        duplicate = await _consume(
            factory,
            message_id=MESSAGE_ONE,
            payload_hash=PAYLOAD_HASH_ONE,
            suffix=903,
        )

        assert duplicate is InboxAction.DUPLICATE

        assert (
            await _effect_count(
                database,
                message_id=MESSAGE_ONE,
            )
            == 1
        )

        # Same identity with another payload must fail closed.
        with pytest.raises(
            InboxMessageConflictError,
            match=("Inbox message is already bound to a different payload"),
        ):
            await _consume(
                factory,
                message_id=MESSAGE_ONE,
                payload_hash=("sha256:" + ("c" * 64)),
                suffix=904,
            )

        assert (
            await _effect_count(
                database,
                message_id=MESSAGE_ONE,
            )
            == 1
        )

        # ----------------------------------------------------------
        # C-I3-15:
        # handler failure rolls back Inbox + business effect.
        # ----------------------------------------------------------

        with pytest.raises(
            RuntimeError,
            match="simulated handler failure",
        ):
            await _consume(
                factory,
                message_id=MESSAGE_RETRY,
                payload_hash=PAYLOAD_HASH_RETRY,
                suffix=911,
                fail_handler=True,
            )

        assert (
            await _effect_count(
                database,
                message_id=MESSAGE_RETRY,
            )
            == 0
        )

        failed_record = await _stored_inbox(
            factory,
            message_id=MESSAGE_RETRY,
            suffix=912,
        )

        assert failed_record is None

        # ----------------------------------------------------------
        # Retry after rollback is a normal first processing attempt.
        # ----------------------------------------------------------

        retry = await _consume(
            factory,
            message_id=MESSAGE_RETRY,
            payload_hash=PAYLOAD_HASH_RETRY,
            suffix=913,
        )

        assert retry is InboxAction.PROCESS

        assert (
            await _effect_count(
                database,
                message_id=MESSAGE_RETRY,
            )
            == 1
        )

        retried_record = await _stored_inbox(
            factory,
            message_id=MESSAGE_RETRY,
            suffix=914,
        )

        assert retried_record is not None
        assert retried_record.processed_at is not None
        assert retried_record.payload_hash == PAYLOAD_HASH_RETRY

        # ----------------------------------------------------------
        # Concurrent duplicate delivery:
        # both transactions observe an absent Inbox record before
        # either attempts registration. The Inbox uniqueness
        # constraint, not the business-effect table, arbitrates the
        # race. Exactly one business effect may commit.
        # ----------------------------------------------------------

        concurrent_message = MessageId(UUID("00000000-0000-7023-8000-000000000001"))
        concurrent_hash = "sha256:" + ("d" * 64)
        barrier = asyncio.Barrier(2)

        first, second = await asyncio.gather(
            _consume(
                factory,
                message_id=concurrent_message,
                payload_hash=concurrent_hash,
                suffix=921,
                race_barrier=barrier,
            ),
            _consume(
                factory,
                message_id=concurrent_message,
                payload_hash=concurrent_hash,
                suffix=922,
                race_barrier=barrier,
            ),
            return_exceptions=True,
        )

        results = (first, second)

        assert sum(result is InboxAction.PROCESS for result in results) == 1
        assert sum(isinstance(result, IntegrityError) for result in results) == 1

        assert (
            await _effect_count(
                database,
                message_id=concurrent_message,
            )
            == 1
        )

        concurrent_stored = await _stored_inbox(
            factory,
            message_id=concurrent_message,
            suffix=923,
        )

        assert concurrent_stored is not None
        assert concurrent_stored.processed_at is not None
        assert concurrent_stored.payload_hash == concurrent_hash

        retry_after_collision = await _consume(
            factory,
            message_id=concurrent_message,
            payload_hash=concurrent_hash,
            suffix=924,
        )

        assert retry_after_collision is InboxAction.DUPLICATE

        assert (
            await _effect_count(
                database,
                message_id=concurrent_message,
            )
            == 1
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
def test_inbox_effectively_once(
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
