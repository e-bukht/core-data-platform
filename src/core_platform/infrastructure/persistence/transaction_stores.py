from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.transaction_schema import (
    audit_record,
    idempotency_record,
    inbox_message,
    outbox_message,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import (
    IdempotencyRecordId,
    InboxRecordId,
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    IdempotencyRecord,
    IdempotencyStatus,
    InboxMessage,
    MessageEnvelope,
    OutboxMessage,
    TransactionContext,
)

ConnectionProvider = Callable[[], AsyncConnection]


def _idempotency_from_row(row: RowMapping) -> IdempotencyRecord:
    return IdempotencyRecord(
        record_id=IdempotencyRecordId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        operation=row["operation"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        status=IdempotencyStatus(row["status"]),
        transaction_id=TransactionId(row["transaction_id"]),
        result_reference=row["result_reference"],
        response_status=row["response_status"],
        response_payload=cast(
            dict[str, object] | None,
            row["response_payload"],
        ),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        expires_at=row["expires_at"],
    )


def _outbox_from_row(row: RowMapping) -> OutboxMessage:
    causation_id = row["causation_id"]

    envelope = MessageEnvelope(
        message_id=MessageId(row["id"]),
        message_type=row["message_type"],
        schema_version=row["schema_version"],
        source=row["source"],
        tenant_id=TenantId(row["tenant_id"]),
        transaction_id=TransactionId(row["transaction_id"]),
        actor_id=ActorId(row["actor_id"]),
        occurred_at=row["occurred_at"],
        correlation_id=CorrelationId(row["correlation_id"]),
        causation_id=(MessageId(causation_id) if causation_id is not None else None),
        aggregate_type=row["aggregate_type"],
        aggregate_id=row["aggregate_id"],
        aggregate_version=row["aggregate_version"],
        payload=cast(dict[str, object], row["payload"]),
        payload_hash=row["payload_hash"],
    )

    return OutboxMessage(
        envelope=envelope,
        available_at=row["available_at"],
        published_at=row["published_at"],
        attempt_count=row["attempt_count"],
        lease_owner=row["lease_owner"],
        lease_until=row["lease_until"],
        last_error=row["last_error"],
    )


def _inbox_from_row(row: RowMapping) -> InboxMessage:
    causation_id = row["causation_id"]

    return InboxMessage(
        record_id=InboxRecordId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        consumer_name=row["consumer_name"],
        message_id=MessageId(row["message_id"]),
        message_type=row["message_type"],
        correlation_id=CorrelationId(row["correlation_id"]),
        causation_id=(MessageId(causation_id) if causation_id is not None else None),
        payload_hash=row["payload_hash"],
        received_at=row["received_at"],
        processed_at=row["processed_at"],
    )


class PostgresIdempotencyStore:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def get(
        self,
        *,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        statement = select(idempotency_record).where(
            idempotency_record.c.tenant_id == self._context.tenant_id.value,
            idempotency_record.c.operation == operation,
            idempotency_record.c.idempotency_key == idempotency_key,
        )

        row = (await self._connection().execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return _idempotency_from_row(row)

    async def add(self, record: IdempotencyRecord) -> None:
        if record.tenant_id != self._context.tenant_id:
            raise ValueError("Idempotency tenant does not match UnitOfWork")
        if record.transaction_id != self._context.transaction_id:
            raise ValueError("Idempotency transaction does not match UnitOfWork")
        if record.operation != self._context.operation:
            raise ValueError("Idempotency operation does not match UnitOfWork")

        await self._connection().execute(
            idempotency_record.insert().values(
                id=record.record_id.value,
                tenant_id=record.tenant_id.value,
                operation=record.operation,
                idempotency_key=record.idempotency_key,
                request_hash=record.request_hash,
                status=record.status.value,
                transaction_id=record.transaction_id.value,
                result_reference=record.result_reference,
                response_status=record.response_status,
                response_payload=(
                    dict(record.response_payload) if record.response_payload is not None else None
                ),
                created_at=record.created_at,
                completed_at=record.completed_at,
                expires_at=record.expires_at,
            )
        )

    async def complete(
        self,
        *,
        operation: str,
        idempotency_key: str,
        result_reference: str | None,
        response_status: int,
        response_payload: dict[str, object] | None,
        completed_at: datetime,
    ) -> IdempotencyRecord:
        statement = (
            update(idempotency_record)
            .where(
                idempotency_record.c.tenant_id == self._context.tenant_id.value,
                idempotency_record.c.operation == operation,
                idempotency_record.c.idempotency_key == idempotency_key,
                idempotency_record.c.status == IdempotencyStatus.IN_PROGRESS.value,
            )
            .values(
                status=IdempotencyStatus.COMPLETED.value,
                result_reference=result_reference,
                response_status=response_status,
                response_payload=response_payload,
                completed_at=completed_at,
            )
            .returning(idempotency_record)
        )

        row = (await self._connection().execute(statement)).mappings().one_or_none()

        if row is None:
            raise RuntimeError("Idempotency record not found or already completed")

        return _idempotency_from_row(row)


class PostgresOutboxStore:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def add(self, message: OutboxMessage) -> None:
        envelope = message.envelope

        if envelope.tenant_id != self._context.tenant_id:
            raise ValueError("Outbox tenant does not match UnitOfWork")
        if envelope.transaction_id != self._context.transaction_id:
            raise ValueError("Outbox transaction does not match UnitOfWork")
        if envelope.actor_id != self._context.actor_id:
            raise ValueError("Outbox actor does not match UnitOfWork")
        if envelope.correlation_id != self._context.correlation_id:
            raise ValueError("Outbox correlation does not match UnitOfWork")

        await self._connection().execute(
            outbox_message.insert().values(
                id=envelope.message_id.value,
                tenant_id=envelope.tenant_id.value,
                transaction_id=envelope.transaction_id.value,
                actor_id=envelope.actor_id.value,
                message_type=envelope.message_type,
                schema_version=envelope.schema_version,
                source=envelope.source,
                occurred_at=envelope.occurred_at,
                available_at=message.available_at,
                published_at=message.published_at,
                correlation_id=envelope.correlation_id.value,
                causation_id=(
                    envelope.causation_id.value if envelope.causation_id is not None else None
                ),
                aggregate_type=envelope.aggregate_type,
                aggregate_id=envelope.aggregate_id,
                aggregate_version=envelope.aggregate_version,
                payload=dict(envelope.payload),
                payload_hash=envelope.payload_hash,
                attempt_count=message.attempt_count,
                lease_owner=message.lease_owner,
                lease_until=message.lease_until,
                last_error=message.last_error,
            )
        )

    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
        limit: int,
    ) -> tuple[OutboxMessage, ...]:
        if limit <= 0:
            raise ValueError("Outbox claim limit must be > 0")
        if lease_until <= now:
            raise ValueError("Outbox lease_until must be after now")

        claimable = (
            select(outbox_message.c.id)
            .where(
                outbox_message.c.tenant_id == self._context.tenant_id.value,
                outbox_message.c.published_at.is_(None),
                outbox_message.c.available_at <= now,
                or_(
                    outbox_message.c.lease_until.is_(None),
                    outbox_message.c.lease_until <= now,
                ),
            )
            .order_by(
                outbox_message.c.available_at,
                outbox_message.c.occurred_at,
                outbox_message.c.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        ids = (await self._connection().execute(claimable)).scalars().all()

        if not ids:
            return ()

        statement = (
            update(outbox_message)
            .where(
                outbox_message.c.tenant_id == self._context.tenant_id.value,
                outbox_message.c.id.in_(ids),
            )
            .values(
                lease_owner=worker_id,
                lease_until=lease_until,
                attempt_count=outbox_message.c.attempt_count + 1,
                last_error=None,
            )
            .returning(outbox_message)
        )

        rows = (await self._connection().execute(statement)).mappings().all()

        by_id = {row["id"]: row for row in rows}

        return tuple(_outbox_from_row(by_id[message_id]) for message_id in ids)

    async def mark_published(
        self,
        *,
        message_id: MessageId,
        worker_id: str,
        expected_attempt: int,
        published_at: datetime,
    ) -> None:
        if expected_attempt <= 0:
            raise ValueError("Outbox expected_attempt must be > 0")

        statement = (
            update(outbox_message)
            .where(
                outbox_message.c.tenant_id == self._context.tenant_id.value,
                outbox_message.c.id == message_id.value,
                outbox_message.c.published_at.is_(None),
                outbox_message.c.lease_owner == worker_id,
                outbox_message.c.attempt_count == expected_attempt,
                outbox_message.c.lease_until.is_not(None),
                outbox_message.c.lease_until >= func.now(),
            )
            .values(
                published_at=published_at,
                lease_owner=None,
                lease_until=None,
                last_error=None,
            )
        )

        result = await self._connection().execute(statement)

        if result.rowcount != 1:
            raise RuntimeError("Outbox lease ownership lost")

    async def release(
        self,
        *,
        message_id: MessageId,
        worker_id: str,
        expected_attempt: int,
        available_at: datetime,
        error: str,
    ) -> None:
        if expected_attempt <= 0:
            raise ValueError("Outbox expected_attempt must be > 0")

        statement = (
            update(outbox_message)
            .where(
                outbox_message.c.tenant_id == self._context.tenant_id.value,
                outbox_message.c.id == message_id.value,
                outbox_message.c.published_at.is_(None),
                outbox_message.c.lease_owner == worker_id,
                outbox_message.c.attempt_count == expected_attempt,
                outbox_message.c.lease_until.is_not(None),
                outbox_message.c.lease_until >= func.now(),
            )
            .values(
                available_at=available_at,
                lease_owner=None,
                lease_until=None,
                last_error=error,
            )
        )

        result = await self._connection().execute(statement)

        if result.rowcount != 1:
            raise RuntimeError("Outbox lease ownership lost")


class PostgresInboxStore:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def get(
        self,
        *,
        consumer_name: str,
        message_id: MessageId,
    ) -> InboxMessage | None:
        statement = select(inbox_message).where(
            inbox_message.c.tenant_id == self._context.tenant_id.value,
            inbox_message.c.consumer_name == consumer_name,
            inbox_message.c.message_id == message_id.value,
        )

        row = (await self._connection().execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return _inbox_from_row(row)

    async def add(self, message: InboxMessage) -> None:
        if message.tenant_id != self._context.tenant_id:
            raise ValueError("Inbox tenant does not match UnitOfWork")

        await self._connection().execute(
            inbox_message.insert().values(
                id=message.record_id.value,
                tenant_id=message.tenant_id.value,
                consumer_name=message.consumer_name,
                message_id=message.message_id.value,
                message_type=message.message_type,
                correlation_id=message.correlation_id.value,
                causation_id=(
                    message.causation_id.value if message.causation_id is not None else None
                ),
                payload_hash=message.payload_hash,
                received_at=message.received_at,
                processed_at=message.processed_at,
            )
        )

    async def mark_processed(
        self,
        *,
        consumer_name: str,
        message_id: MessageId,
        processed_at: datetime,
    ) -> None:
        statement = (
            update(inbox_message)
            .where(
                inbox_message.c.tenant_id == self._context.tenant_id.value,
                inbox_message.c.consumer_name == consumer_name,
                inbox_message.c.message_id == message_id.value,
                inbox_message.c.processed_at.is_(None),
            )
            .values(processed_at=processed_at)
        )

        result = await self._connection().execute(statement)

        if result.rowcount != 1:
            raise RuntimeError("Inbox message not found or already processed")


class PostgresAuditStore:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def append(self, record: AuditRecord) -> None:
        if record.tenant_id != self._context.tenant_id:
            raise ValueError("Audit tenant does not match UnitOfWork")
        if record.transaction_id != self._context.transaction_id:
            raise ValueError("Audit transaction does not match UnitOfWork")
        if record.actor_id != self._context.actor_id:
            raise ValueError("Audit actor does not match UnitOfWork")
        if record.correlation_id != self._context.correlation_id:
            raise ValueError("Audit correlation does not match UnitOfWork")

        await self._connection().execute(
            audit_record.insert().values(
                id=record.record_id.value,
                tenant_id=record.tenant_id.value,
                transaction_id=record.transaction_id.value,
                actor_id=record.actor_id.value,
                correlation_id=record.correlation_id.value,
                capability=record.capability,
                action=record.action,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                outcome=AuditOutcome(record.outcome).value,
                occurred_at=record.occurred_at,
                details=dict(record.details),
            )
        )
