from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SqlUuid

metadata = MetaData(schema="platform")

TENANT_SCOPED_TABLES = ("tenant_membership", "capability_grant")


tenant = Table(
    "tenant",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column("code", String(80), nullable=False, unique=True),
    Column("display_name", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

actor = Table(
    "actor",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column("actor_type", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("display_name", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

external_identity = Table(
    "external_identity",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column("provider_type", String(32), nullable=False),
    Column("issuer", String(500), nullable=False),
    Column("subject", String(255), nullable=False),
    Column("actor_id", SqlUuid(as_uuid=True), ForeignKey("platform.actor.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("metadata", JSON, nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
)

tenant_membership = Table(
    "tenant_membership",
    metadata,
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.tenant.id"),
        primary_key=True,
    ),
    Column(
        "actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.actor.id"),
        primary_key=True,
    ),
    Column("status", String(32), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("version", BigInteger, nullable=False),
)

capability = Table(
    "capability",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column("code", String(160), nullable=False, unique=True),
    Column("description", String(500), nullable=False),
    Column("risk_class", String(32), nullable=False),
    Column("status", String(32), nullable=False),
)

capability_grant = Table(
    "capability_grant",
    metadata,
    Column("id", SqlUuid(as_uuid=True), primary_key=True),
    Column("tenant_id", SqlUuid(as_uuid=True), ForeignKey("platform.tenant.id"), nullable=False),
    Column("actor_id", SqlUuid(as_uuid=True), ForeignKey("platform.actor.id"), nullable=False),
    Column(
        "capability_id",
        SqlUuid(as_uuid=True),
        ForeignKey("platform.capability.id"),
        nullable=False,
    ),
    Column("status", String(32), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id",
        "actor_id",
        "capability_id",
        name="uq_capability_grant_subject_capability",
    ),
)
