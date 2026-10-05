from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.dialects.postgresql import JSONB

from core_platform.infrastructure.persistence.context_trust_schema import (
    metadata,
)

TRANSACTION_TENANT_SCOPED_TABLES = (
    "idempotency_record",
    "outbox_message",
    "inbox_message",
    "audit_record",
)


idempotency_record = Table(
    "idempotency_record",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id"),
        nullable=False,
    ),
    Column("operation", String(160), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("request_hash", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("transaction_id", SqlUuid(as_uuid=True), nullable=False),
    Column("result_reference", String(500), nullable=True),
    Column("response_status", Integer, nullable=True),
    Column("response_payload", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "operation",
        "idempotency_key",
        name="uq_idempotency_record_key",
    ),
    CheckConstraint(
        "status IN ('IN_PROGRESS', 'COMPLETED')",
        name="ck_idempotency_record_status",
    ),
)


outbox_message = Table(
    "outbox_message",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id"),
        nullable=False,
    ),
    Column("transaction_id", SqlUuid(as_uuid=True), nullable=False),
    Column(
        "actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.actor.id"),
        nullable=False,
    ),
    Column("message_type", String(240), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("source", String(240), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("correlation_id", SqlUuid(as_uuid=True), nullable=False),
    Column("causation_id", SqlUuid(as_uuid=True), nullable=True),
    Column("aggregate_type", String(160), nullable=True),
    Column("aggregate_id", String(255), nullable=True),
    Column("aggregate_version", BigInteger, nullable=True),
    Column("payload", JSONB, nullable=False),
    Column("payload_hash", String(80), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("lease_owner", String(200), nullable=True),
    Column("lease_until", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
)


inbox_message = Table(
    "inbox_message",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id"),
        nullable=False,
    ),
    Column("consumer_name", String(200), nullable=False),
    Column("message_id", SqlUuid(as_uuid=True), nullable=False),
    Column("message_type", String(240), nullable=False),
    Column("correlation_id", SqlUuid(as_uuid=True), nullable=False),
    Column("causation_id", SqlUuid(as_uuid=True), nullable=True),
    Column("payload_hash", String(80), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id",
        "consumer_name",
        "message_id",
        name="uq_inbox_message_consumer",
    ),
)


audit_record = Table(
    "audit_record",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id"),
        nullable=False,
    ),
    Column("transaction_id", SqlUuid(as_uuid=True), nullable=False),
    Column(
        "actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.actor.id"),
        nullable=False,
    ),
    Column("correlation_id", SqlUuid(as_uuid=True), nullable=False),
    Column("capability", String(240), nullable=False),
    Column("action", String(240), nullable=False),
    Column("resource_type", String(160), nullable=False),
    Column("resource_id", String(255), nullable=True),
    Column("outcome", String(32), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("details", JSONB, nullable=False),
    UniqueConstraint(
        "tenant_id",
        "id",
        "transaction_id",
        "actor_id",
        "correlation_id",
        name="uq_audit_record_evidence_identity",
    ),
)


Index(
    "ix_idempotency_record_transaction",
    idempotency_record.c.tenant_id,
    idempotency_record.c.transaction_id,
)

Index(
    "ix_audit_record_transaction",
    audit_record.c.tenant_id,
    audit_record.c.transaction_id,
)
