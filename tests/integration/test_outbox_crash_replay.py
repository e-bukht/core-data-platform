from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
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
from core_platform.transaction_kernel.hashing import JsonValue
from core_platform.transaction_kernel.ids import (
    InboxRecordId,
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.inbox import (
    InboxAction,
    evaluate_inbox,
)
from core_platform.transaction_kernel.message_envelope import (
    create_message_envelope,
)
from core_platform.transaction_kernel.models import (
    InboxMessage,
    MessageEnvelope,
    OutboxMessage,
    TransactionContext,
)
from core_platform.transaction_kernel.ports import MessagePublisher
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000001101"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000001102"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000001103"))
MESSAGE_ID = MessageId(UUID("00000000-0000-7000-8000-000000001104"))

CONSUMER_NAME = "c-i3-20-consumer"


class RecordingPublisher:
    def __init__(self) -> None:
        self.deliveries: list[MessageEnvelope] = []

    async def publish(
        self,
        envelope: MessageEnvelope,
    ) -> None:
        self.deliveries.append(envelope)


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
                        'replay-test-tenant',
                        'Replay Test Tenant',
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
                        'Replay Test Actor'
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
                    CREATE TABLE transaction_test.replay_effect (
                        id uuid PRIMARY KEY,
                        tenant_id uuid NOT NULL,
                        message_id uuid NOT NULL,
                        effect_value varchar(100) NOT NULL
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE transaction_test.replay_effect
                    ENABLE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    ALTER TABLE transaction_test.replay_effect
                    FORCE ROW LEVEL SECURITY
                    """
                )
            )

            connection.execute(
                text(
                    """
                    CREATE POLICY replay_effect_tenant_isolation
                    ON transaction_test.replay_effect
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
                    ON transaction_test.replay_effect
                    TO coredata_runtime
                    """
                )
            )
    finally:
        engine.dispose()


def _context(
    suffix: int,
    *,
    operation: str,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(UUID(f"00000000-0000-7110-8000-{suffix:012d}")),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation=operation,
        capability=operation,
        started_at=datetime.now(UTC),
    )


async def _create_outbox(
    factory: PostgresUnitOfWorkFactory,
) -> MessageEnvelope:
    context = _context(
        1101,
        operation="replay.produce",
    )

    payload: dict[str, JsonValue] = {
        "order_id": "ORD-REPLAY-1",
        "status": "CONFIRMED",
    }

    occurred_at = datetime.now(UTC)

    envelope = create_message_envelope(
        context=context,
        message_id=MESSAGE_ID,
        message_type="order.confirmed",
        schema_version=1,
        source="core-data-platform",
        occurred_at=occurred_at,
        aggregate_type="Order",
        aggregate_id="ORD-REPLAY-1",
        aggregate_version=1,
        payload=payload,
    )

    uow = factory.create(context)
    assert isinstance(uow, PostgresUnitOfWork)

    async with uow as active:
        await active.outbox.add(
            OutboxMessage(
                envelope=envelope,
                available_at=occurred_at,
                published_at=None,
                attempt_count=0,
                lease_owner=None,
                lease_until=None,
                last_error=None,
            )
        )
        await active.commit()

    return envelope


async def _claim_one(
    factory: PostgresUnitOfWorkFactory,
    *,
    suffix: int,
    worker_id: str,
    now: datetime,
    lease_until: datetime,
) -> OutboxMessage:
    context = _context(
        suffix,
        operation="outbox.dispatch",
    )

    uow = factory.create(context)
    assert isinstance(uow, PostgresUnitOfWork)

    async with uow as active:
        claimed = await active.outbox.claim_ready(
            worker_id=worker_id,
            now=now,
            lease_until=lease_until,
            limit=1,
        )

        assert len(claimed) == 1

        await active.commit()

        return claimed[0]


async def _mark_published(
    factory: PostgresUnitOfWorkFactory,
    *,
    message: OutboxMessage,
    worker_id: str,
    suffix: int,
) -> None:
    context = _context(
        suffix,
        operation="outbox.dispatch",
    )

    uow = factory.create(context)
    assert isinstance(uow, PostgresUnitOfWork)

    async with uow as active:
        await active.outbox.mark_published(
            message_id=message.envelope.message_id,
            worker_id=worker_id,
            expected_attempt=message.attempt_count,
            published_at=datetime.now(UTC),
        )
        await active.commit()


async def _consume_delivery(
    factory: PostgresUnitOfWorkFactory,
    *,
    envelope: MessageEnvelope,
    suffix: int,
) -> InboxAction:
    context = _context(
        suffix,
        operation="message.consume",
    )

    uow = factory.create(context)
    assert isinstance(uow, PostgresUnitOfWork)

    async with uow as active:
        existing = await active.inbox.get(
            consumer_name=CONSUMER_NAME,
            message_id=envelope.message_id,
        )

        decision = evaluate_inbox(
            existing=existing,
            consumer_name=CONSUMER_NAME,
            message_id=envelope.message_id,
            payload_hash=envelope.payload_hash,
        )

        if decision.action is InboxAction.DUPLICATE:
            return decision.action

        assert decision.action is InboxAction.PROCESS

        await active.inbox.add(
            InboxMessage(
                record_id=InboxRecordId(UUID(f"00000000-0000-7111-8000-{suffix:012d}")),
                tenant_id=envelope.tenant_id,
                consumer_name=CONSUMER_NAME,
                message_id=envelope.message_id,
                message_type=envelope.message_type,
                correlation_id=envelope.correlation_id,
                causation_id=envelope.causation_id,
                payload_hash=envelope.payload_hash,
                received_at=datetime.now(UTC),
                processed_at=None,
            )
        )

        connection = active._require_connection()

        await connection.execute(
            text(
                """
                INSERT INTO transaction_test.replay_effect (
                    id,
                    tenant_id,
                    message_id,
                    effect_value
                )
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    CAST(:message_id AS uuid),
                    'applied'
                )
                """
            ),
            {
                "id": (f"00000000-0000-7112-8000-{suffix:012d}"),
                "tenant_id": str(envelope.tenant_id.value),
                "message_id": str(envelope.message_id.value),
            },
        )

        await active.inbox.mark_processed(
            consumer_name=CONSUMER_NAME,
            message_id=envelope.message_id,
            processed_at=datetime.now(UTC),
        )

        await active.commit()

        return InboxAction.PROCESS


async def _effect_count(
    database: Database,
) -> int:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        result = await connection.execute(
            text(
                """
                SELECT count(*)
                FROM transaction_test.replay_effect
                WHERE message_id =
                    CAST(:message_id AS uuid)
                """
            ),
            {"message_id": str(MESSAGE_ID.value)},
        )

        return int(result.scalar_one())


async def _outbox_state(
    database: Database,
) -> tuple[datetime | None, int, str | None]:
    async with database.tenant_transaction(TENANT_ID.value) as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT
                        published_at,
                        attempt_count,
                        lease_owner
                    FROM platform.outbox_message
                    WHERE id =
                        CAST(:message_id AS uuid)
                    """
                ),
                {"message_id": str(MESSAGE_ID.value)},
            )
        ).one()

        return (
            row[0],
            int(row[1]),
            row[2],
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

    publisher: MessagePublisher = RecordingPublisher()
    assert isinstance(publisher, RecordingPublisher)

    try:
        original = await _create_outbox(factory)

        # ----------------------------------------------------------
        # Delivery attempt 1.
        # ----------------------------------------------------------

        first_now = datetime.now(UTC)
        first_lease_until = first_now + timedelta(minutes=5)

        first_claim = await _claim_one(
            factory,
            suffix=1102,
            worker_id="worker-1",
            now=first_now,
            lease_until=first_lease_until,
        )

        assert first_claim.attempt_count == 1
        assert first_claim.lease_owner == "worker-1"
        assert first_claim.envelope.message_id == (original.message_id)

        await publisher.publish(first_claim.envelope)

        # Crash point:
        # broker accepted publication, but worker dies before
        # mark_published(). Outbox remains unpublished/leased.

        first_delivery = publisher.deliveries[0]

        first_action = await _consume_delivery(
            factory,
            envelope=first_delivery,
            suffix=1103,
        )

        assert first_action is InboxAction.PROCESS
        assert await _effect_count(database) == 1

        state_after_crash = await _outbox_state(database)

        assert state_after_crash[0] is None
        assert state_after_crash[1] == 1
        assert state_after_crash[2] == "worker-1"

        # ----------------------------------------------------------
        # Advance logical dispatcher clock beyond first lease.
        # No wall-clock sleep is required.
        # ----------------------------------------------------------

        retry_now = first_lease_until + timedelta(seconds=1)
        retry_lease_until = retry_now + timedelta(hours=1)

        second_claim = await _claim_one(
            factory,
            suffix=1104,
            worker_id="worker-2",
            now=retry_now,
            lease_until=retry_lease_until,
        )

        assert second_claim.attempt_count == 2
        assert second_claim.lease_owner == "worker-2"

        assert second_claim.envelope.message_id == first_claim.envelope.message_id
        assert second_claim.envelope.payload_hash == first_claim.envelope.payload_hash

        # ----------------------------------------------------------
        # At-least-once transport:
        # same durable message is published again.
        # ----------------------------------------------------------

        await publisher.publish(second_claim.envelope)

        assert len(publisher.deliveries) == 2

        assert publisher.deliveries[0].message_id == publisher.deliveries[1].message_id

        # ----------------------------------------------------------
        # Effectively-once business effect:
        # Inbox recognizes the second delivery as duplicate.
        # ----------------------------------------------------------

        second_action = await _consume_delivery(
            factory,
            envelope=publisher.deliveries[1],
            suffix=1105,
        )

        assert second_action is InboxAction.DUPLICATE

        assert await _effect_count(database) == 1

        # ----------------------------------------------------------
        # Successful second dispatcher owns attempt 2 and can
        # finally mark the Outbox message published.
        # ----------------------------------------------------------

        await _mark_published(
            factory,
            message=second_claim,
            worker_id="worker-2",
            suffix=1106,
        )

        final_state = await _outbox_state(database)

        assert final_state[0] is not None
        assert final_state[1] == 2
        assert final_state[2] is None

        # Published messages are no longer claimable.
        final_now = retry_lease_until + timedelta(seconds=1)

        context = _context(
            1107,
            operation="outbox.dispatch",
        )
        uow = factory.create(context)
        assert isinstance(
            uow,
            PostgresUnitOfWork,
        )

        async with uow as active:
            remaining = await active.outbox.claim_ready(
                worker_id="worker-3",
                now=final_now,
                lease_until=(final_now + timedelta(minutes=5)),
                limit=1,
            )

            assert remaining == ()

            await active.rollback()

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
def test_outbox_crash_retry_replay_effectively_once(
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
