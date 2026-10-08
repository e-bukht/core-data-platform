from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from tests.test_platform.messaging import RecordingMessageTransport

from core_platform.platform_kernel.context import ExecutionContext
from core_platform.transaction_kernel.ids import MessageId, TransactionId
from core_platform.transaction_kernel.message_envelope import create_message_envelope
from core_platform.transaction_kernel.models import TransactionContext
from core_platform.transaction_kernel.ports import MessagePublisher


def test_certification_message_transport_records_ordered_deliveries(
    cert_instant: datetime,
    cert_execution_context: ExecutionContext,
    cert_message_transport: RecordingMessageTransport,
) -> None:
    transaction = TransactionContext(
        transaction_id=TransactionId(UUID("00000000-0000-7000-8000-00000000c201")),
        tenant_id=cert_execution_context.tenant_id,
        actor_id=cert_execution_context.actor_id,
        correlation_id=cert_execution_context.correlation_id,
        operation="certification.messaging",
        capability="platform.certification.read",
        started_at=cert_instant,
    )

    envelope = create_message_envelope(
        context=transaction,
        message_id=MessageId(UUID("00000000-0000-7000-8000-00000000c202")),
        message_type="certification.message",
        schema_version=1,
        source="test-platform",
        occurred_at=cert_instant,
        payload={"certified": True},
    )

    publisher: MessagePublisher = cert_message_transport

    asyncio.run(publisher.publish(envelope))

    assert cert_message_transport.deliveries == (envelope,)

    cert_message_transport.clear()

    assert not cert_message_transport.deliveries
