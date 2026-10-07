from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from core_platform.infrastructure.persistence.database import Database
from core_platform.platform_kernel.evidence.models import EvidenceRecord
from core_platform.transaction_kernel.models import (
    AuditRecord,
    InboxMessage,
    OutboxMessage,
)


async def assert_audit_persisted(
    database: Database,
    record: AuditRecord,
) -> None:
    async with database.tenant_transaction(record.tenant_id.value) as connection:
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


async def assert_evidence_persisted(
    database: Database,
    record: EvidenceRecord,
) -> None:
    envelope = record.envelope

    async with database.tenant_transaction(envelope.tenant_id.value) as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT
                            id,
                            tenant_id,
                            audit_record_id,
                            transaction_id,
                            actor_id,
                            correlation_id,
                            envelope_version,
                            evidence_type,
                            occurred_at,
                            signed_at,
                            payload_hash,
                            signature_algorithm,
                            key_id,
                            canonical_payload,
                            signature
                        FROM platform.evidence_record
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": str(envelope.record_id.value)},
                )
            )
            .mappings()
            .one()
        )

    assert row["id"] == envelope.record_id.value
    assert row["tenant_id"] == envelope.tenant_id.value
    assert row["audit_record_id"] == envelope.audit_record_id
    assert row["transaction_id"] == envelope.transaction_id
    assert row["actor_id"] == envelope.actor_id.value
    assert row["correlation_id"] == envelope.correlation_id.value
    assert row["envelope_version"] == envelope.envelope_version
    assert row["evidence_type"] == envelope.evidence_type
    assert row["occurred_at"] == envelope.occurred_at
    assert row["signed_at"] == envelope.signed_at
    assert row["payload_hash"] == envelope.payload_hash
    assert row["signature_algorithm"] == envelope.signature_algorithm
    assert row["key_id"] == envelope.key_id
    assert bytes(row["canonical_payload"]) == record.canonical_payload
    assert bytes(row["signature"]) == record.signature

async def assert_outbox_persisted(
    database: Database,
    message: OutboxMessage,
) -> None:
    envelope = message.envelope

    async with database.tenant_transaction(envelope.tenant_id.value) as connection:
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
                            message_type,
                            schema_version,
                            source,
                            occurred_at,
                            available_at,
                            published_at,
                            correlation_id,
                            causation_id,
                            aggregate_type,
                            aggregate_id,
                            aggregate_version,
                            payload,
                            payload_hash,
                            attempt_count,
                            lease_owner,
                            lease_until,
                            last_error
                        FROM platform.outbox_message
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": str(envelope.message_id.value)},
                )
            )
            .mappings()
            .one()
        )

    assert row["id"] == envelope.message_id.value
    assert row["tenant_id"] == envelope.tenant_id.value
    assert row["transaction_id"] == envelope.transaction_id.value
    assert row["actor_id"] == envelope.actor_id.value
    assert row["message_type"] == envelope.message_type
    assert row["schema_version"] == envelope.schema_version
    assert row["source"] == envelope.source
    assert row["occurred_at"] == envelope.occurred_at
    assert row["available_at"] == message.available_at
    assert row["published_at"] == message.published_at
    assert row["correlation_id"] == envelope.correlation_id.value
    assert row["causation_id"] == (
        envelope.causation_id.value
        if envelope.causation_id is not None
        else None
    )
    assert row["aggregate_type"] == envelope.aggregate_type
    assert row["aggregate_id"] == envelope.aggregate_id
    assert row["aggregate_version"] == envelope.aggregate_version
    assert row["payload"] == dict(envelope.payload)
    assert row["payload_hash"] == envelope.payload_hash
    assert row["attempt_count"] == message.attempt_count
    assert row["lease_owner"] == message.lease_owner
    assert row["lease_until"] == message.lease_until
    assert row["last_error"] == message.last_error


async def assert_inbox_persisted(
    database: Database,
    message: InboxMessage,
) -> None:
    async with database.tenant_transaction(message.tenant_id.value) as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT
                            id,
                            tenant_id,
                            consumer_name,
                            message_id,
                            message_type,
                            correlation_id,
                            causation_id,
                            payload_hash,
                            received_at,
                            processed_at
                        FROM platform.inbox_message
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": str(message.record_id.value)},
                )
            )
            .mappings()
            .one()
        )

    assert row["id"] == message.record_id.value
    assert row["tenant_id"] == message.tenant_id.value
    assert row["consumer_name"] == message.consumer_name
    assert row["message_id"] == message.message_id.value
    assert row["message_type"] == message.message_type
    assert row["correlation_id"] == message.correlation_id.value
    assert row["causation_id"] == (
        message.causation_id.value
        if message.causation_id is not None
        else None
    )
    assert row["payload_hash"] == message.payload_hash
    assert row["received_at"] == message.received_at
    assert row["processed_at"] == message.processed_at

async def assert_cross_tenant_denied(
    database: Database,
    acting_tenant_id: UUID,
    operation: Callable[[AsyncConnection], Awaitable[object]],
) -> None:
    """Assert that PostgreSQL RLS rejects a cross-tenant operation."""

    with pytest.raises(DBAPIError):
        async with database.tenant_transaction(acting_tenant_id) as connection:
            await operation(connection)