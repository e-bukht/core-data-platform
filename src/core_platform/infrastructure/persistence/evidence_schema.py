from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
)
from sqlalchemy import Uuid as SqlUuid

from core_platform.infrastructure.persistence.context_trust_schema import (
    metadata,
)
from core_platform.infrastructure.persistence.transaction_schema import (
    audit_record,
)

EVIDENCE_TENANT_SCOPED_TABLES = ("evidence_record",)


evidence_record = Table(
    "evidence_record",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("audit_record_id", SqlUuid(as_uuid=True), nullable=False),
    Column("transaction_id", SqlUuid(as_uuid=True), nullable=False),
    Column(
        "actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.actor.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("correlation_id", SqlUuid(as_uuid=True), nullable=False),
    Column("envelope_version", Integer, nullable=False),
    Column("evidence_type", String(160), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("signed_at", DateTime(timezone=True), nullable=False),
    Column("payload_hash", String(80), nullable=False),
    Column("signature_algorithm", String(64), nullable=False),
    Column("key_id", String(255), nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("signature", LargeBinary, nullable=False),
    ForeignKeyConstraint(
        [
            "tenant_id",
            "audit_record_id",
            "transaction_id",
            "actor_id",
            "correlation_id",
        ],
        [
            audit_record.c.tenant_id,
            audit_record.c.id,
            audit_record.c.transaction_id,
            audit_record.c.actor_id,
            audit_record.c.correlation_id,
        ],
        name="fk_evidence_record_audit_context",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "envelope_version >= 1",
        name="ck_evidence_record_envelope_version",
    ),
    CheckConstraint(
        "length(btrim(evidence_type)) > 0",
        name="ck_evidence_record_type",
    ),
    CheckConstraint(
        "signed_at >= occurred_at",
        name="ck_evidence_record_signed_at",
    ),
    CheckConstraint(
        "payload_hash ~ '^sha256:[0-9a-f]{64}$'",
        name="ck_evidence_record_payload_hash",
    ),
    CheckConstraint(
        "length(btrim(signature_algorithm)) > 0",
        name="ck_evidence_record_signature_algorithm",
    ),
    CheckConstraint(
        "length(btrim(key_id)) > 0",
        name="ck_evidence_record_key_id",
    ),
    CheckConstraint(
        "octet_length(canonical_payload) > 0",
        name="ck_evidence_record_payload_not_empty",
    ),
    CheckConstraint(
        "octet_length(signature) > 0",
        name="ck_evidence_record_signature_not_empty",
    ),
)


Index(
    "ix_evidence_record_audit",
    evidence_record.c.tenant_id,
    evidence_record.c.audit_record_id,
)

Index(
    "ix_evidence_record_transaction",
    evidence_record.c.tenant_id,
    evidence_record.c.transaction_id,
)

Index(
    "ix_evidence_record_correlation",
    evidence_record.c.tenant_id,
    evidence_record.c.correlation_id,
)

Index(
    "ix_evidence_record_signed_at",
    evidence_record.c.tenant_id,
    evidence_record.c.signed_at,
)