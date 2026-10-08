from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import (
    InboxRecordId,
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.message_envelope import (
    create_message_envelope,
)
from core_platform.transaction_kernel.models import (
    InboxMessage,
    OutboxMessage,
    TransactionContext,
)
from tests.test_platform.assertions import (
    assert_inbox_persisted,
    assert_outbox_persisted,
)
from tests.test_platform.postgres import CertificationPostgres

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-00000000c401"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-00000000c402"))
TRANSACTION_ID = TransactionId(UUID("00000000-0000-7000-8000-00000000c403"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-00000000c404"))
MESSAGE_ID = MessageId(UUID("00000000-0000-7000-8000-00000000c405"))
INBOX_ID = InboxRecordId(UUID("00000000-0000-7000-8000-00000000c406"))

NOW = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="certification.messaging",
        capability="platform.certification.read",
        started_at=NOW,
    )


def _seed_principals(
    postgres: CertificationPostgres,
) -> None:
    engine = create_engine(postgres.migration_url)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO platform.tenant(
                        id,
                        code,
                        display_name,
                        status
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        'certification-messaging',
                        'Certification Messaging',
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_id": str(TENANT_ID.value),
                },
            )

            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor(
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'SERVICE',
                        'ACTIVE',
                        'Certification Messaging Actor'
                    )
                    """
                ),
                {
                    "actor_id": str(ACTOR_ID.value),
                },
            )
    finally:
        engine.dispose()


async def _persist_and_assert(
    postgres: CertificationPostgres,
) -> None:
    context = _context()

    envelope = create_message_envelope(
        context=context,
        message_id=MESSAGE_ID,
        message_type="certification.message",
        schema_version=1,
        source="test-platform",
        occurred_at=NOW,
        aggregate_type="CertificationProbe",
        aggregate_id="probe-1",
        aggregate_version=1,
        payload={
            "certified": True,
            "sequence": 1,
        },
    )

    outbox = OutboxMessage(
        envelope=envelope,
        available_at=NOW,
        published_at=None,
        attempt_count=0,
        lease_owner=None,
        lease_until=None,
        last_error=None,
    )

    inbox = InboxMessage(
        record_id=INBOX_ID,
        tenant_id=context.tenant_id,
        consumer_name="certification-consumer",
        message_id=envelope.message_id,
        message_type=envelope.message_type,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.causation_id,
        payload_hash=envelope.payload_hash,
        received_at=NOW,
        processed_at=None,
    )

    factory = PostgresUnitOfWorkFactory(postgres.database)

    uow = factory.create(context)

    assert isinstance(
        uow,
        PostgresUnitOfWork,
    )

    async with uow as active:
        await active.outbox.add(outbox)
        await active.inbox.add(inbox)
        await active.commit()

    await assert_outbox_persisted(
        postgres.database,
        outbox,
    )

    await assert_inbox_persisted(
        postgres.database,
        inbox,
    )


@pytest.mark.integration
def test_reusable_outbox_and_inbox_assertions(
    cert_postgres: CertificationPostgres,
) -> None:
    _seed_principals(cert_postgres)

    asyncio.run(_persist_and_assert(cert_postgres))
