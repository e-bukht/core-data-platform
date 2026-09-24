from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    IdempotencyRecordId,
    InboxRecordId,
    MessageId,
    TransactionId,
)


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class AuditOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    FAILURE = "FAILURE"


@dataclass(frozen=True, slots=True)
class TransactionContext:
    transaction_id: TransactionId
    tenant_id: TenantId
    actor_id: ActorId
    correlation_id: CorrelationId
    operation: str
    capability: str
    started_at: datetime
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    record_id: IdempotencyRecordId
    tenant_id: TenantId
    operation: str
    idempotency_key: str
    request_hash: str
    status: IdempotencyStatus
    transaction_id: TransactionId
    result_reference: str | None
    response_status: int | None
    response_payload: Mapping[str, object] | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    message_id: MessageId
    message_type: str
    schema_version: int
    source: str
    tenant_id: TenantId
    transaction_id: TransactionId
    actor_id: ActorId
    occurred_at: datetime
    correlation_id: CorrelationId
    causation_id: MessageId | None
    aggregate_type: str | None
    aggregate_id: str | None
    aggregate_version: int | None
    payload: Mapping[str, object]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    envelope: MessageEnvelope
    available_at: datetime
    published_at: datetime | None
    attempt_count: int
    lease_owner: str | None
    lease_until: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class InboxMessage:
    record_id: InboxRecordId
    tenant_id: TenantId
    consumer_name: str
    message_id: MessageId
    message_type: str
    correlation_id: CorrelationId
    causation_id: MessageId | None
    payload_hash: str
    received_at: datetime
    processed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    record_id: AuditRecordId
    tenant_id: TenantId
    transaction_id: TransactionId
    actor_id: ActorId
    correlation_id: CorrelationId
    capability: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: AuditOutcome
    occurred_at: datetime
    details: Mapping[str, object]
