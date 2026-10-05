from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.dialects.postgresql import ARRAY

from core_platform.infrastructure.persistence.context_trust_schema import (
    metadata,
)

BREAK_GLASS_TENANT_SCOPED_TABLES = (
    "break_glass_grant",
)


break_glass_grant = Table(
    "break_glass_grant",
    metadata,
    Column(
        "id",
        SqlUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        ForeignKey(
            "platform.tenant.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey(
            "platform.actor.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "issued_by_actor_id",
        SqlUuid(as_uuid=True),
        ForeignKey(
            "platform.actor.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "capabilities",
        ARRAY(String(160)),
        nullable=False,
    ),
    Column(
        "scope_kind",
        String(32),
        nullable=False,
    ),
    Column(
        "resource_type",
        String(160),
        nullable=True,
    ),
    Column(
        "resource_id",
        String(255),
        nullable=True,
    ),
    Column(
        "reason",
        String(2000),
        nullable=False,
    ),
    Column(
        "valid_from",
        DateTime(timezone=True),
        nullable=False,
    ),
    Column(
        "valid_until",
        DateTime(timezone=True),
        nullable=False,
    ),
    Column(
        "status",
        String(32),
        nullable=False,
    ),
    Column(
        "accepted_acr_values",
        ARRAY(String(255)),
        nullable=False,
    ),
    Column(
        "required_amr",
        ARRAY(String(128)),
        nullable=False,
    ),
    Column(
        "version",
        BigInteger,
        nullable=False,
        server_default=text("0"),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    CheckConstraint(
        "cardinality(capabilities) > 0",
        name="ck_break_glass_grant_capabilities",
    ),
    CheckConstraint(
        """
        scope_kind IN (
            'TENANT',
            'RESOURCE_TYPE',
            'RESOURCE'
        )
        """,
        name="ck_break_glass_grant_scope_kind",
    ),
    CheckConstraint(
        """
        (
            scope_kind = 'TENANT'
            AND resource_type IS NULL
            AND resource_id IS NULL
        )
        OR (
            scope_kind = 'RESOURCE_TYPE'
            AND resource_type IS NOT NULL
            AND length(btrim(resource_type)) > 0
            AND resource_id IS NULL
        )
        OR (
            scope_kind = 'RESOURCE'
            AND resource_type IS NOT NULL
            AND length(btrim(resource_type)) > 0
            AND resource_id IS NOT NULL
            AND length(btrim(resource_id)) > 0
        )
        """,
        name="ck_break_glass_grant_scope",
    ),
    CheckConstraint(
        "length(btrim(reason)) > 0",
        name="ck_break_glass_grant_reason",
    ),
    CheckConstraint(
        "valid_until > valid_from",
        name="ck_break_glass_grant_validity",
    ),
    CheckConstraint(
        """
        status IN (
            'ACTIVE',
            'SUSPENDED',
            'REVOKED'
        )
        """,
        name="ck_break_glass_grant_status",
    ),
    CheckConstraint(
        """
        cardinality(accepted_acr_values) > 0
        OR cardinality(required_amr) > 0
        """,
        name="ck_break_glass_grant_assurance",
    ),
    CheckConstraint(
        "version >= 0",
        name="ck_break_glass_grant_version",
    ),
)


Index(
    "ix_break_glass_grant_subject",
    break_glass_grant.c.tenant_id,
    break_glass_grant.c.actor_id,
    break_glass_grant.c.status,
)

Index(
    "ix_break_glass_grant_expiry",
    break_glass_grant.c.tenant_id,
    break_glass_grant.c.valid_until,
)

Index(
    "ix_break_glass_grant_issuer",
    break_glass_grant.c.tenant_id,
    break_glass_grant.c.issued_by_actor_id,
)

Index(
    "ix_break_glass_grant_capabilities",
    break_glass_grant.c.capabilities,
    postgresql_using="gin",
)