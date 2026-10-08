"""Cryptographically verifiable Evidence persistence.

Revision ID: 0004_evidence
Revises: 0003_transaction_kernel
"""

from __future__ import annotations

from alembic import op

revision = "0004_evidence"
down_revision = "0003_transaction_kernel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform.audit_record
        ADD CONSTRAINT uq_audit_record_evidence_identity
        UNIQUE (
            tenant_id,
            id,
            transaction_id,
            actor_id,
            correlation_id
        )
        """
    )

    op.execute(
        """
        CREATE TABLE platform.evidence_record (
            id uuid PRIMARY KEY,

            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id) ON DELETE RESTRICT,

            audit_record_id uuid NOT NULL,
            transaction_id uuid NOT NULL,

            actor_id uuid NOT NULL
                REFERENCES platform.actor(id) ON DELETE RESTRICT,

            correlation_id uuid NOT NULL,

            envelope_version integer NOT NULL
                CHECK (envelope_version >= 1),

            evidence_type varchar(160) NOT NULL
                CHECK (length(btrim(evidence_type)) > 0),

            occurred_at timestamptz NOT NULL,
            signed_at timestamptz NOT NULL
                CHECK (signed_at >= occurred_at),

            payload_hash varchar(80) NOT NULL
                CHECK (
                    payload_hash ~ '^sha256:[0-9a-f]{64}$'
                ),

            signature_algorithm varchar(64) NOT NULL
                CHECK (length(btrim(signature_algorithm)) > 0),

            key_id varchar(255) NOT NULL
                CHECK (length(btrim(key_id)) > 0),

            canonical_payload bytea NOT NULL
                CHECK (octet_length(canonical_payload) > 0),

            signature bytea NOT NULL
                CHECK (octet_length(signature) > 0),

            CONSTRAINT fk_evidence_record_audit_context
                FOREIGN KEY (
                    tenant_id,
                    audit_record_id,
                    transaction_id,
                    actor_id,
                    correlation_id
                )
                REFERENCES platform.audit_record (
                    tenant_id,
                    id,
                    transaction_id,
                    actor_id,
                    correlation_id
                )
                ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_evidence_record_audit
        ON platform.evidence_record (
            tenant_id,
            audit_record_id
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_evidence_record_transaction
        ON platform.evidence_record (
            tenant_id,
            transaction_id
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_evidence_record_correlation
        ON platform.evidence_record (
            tenant_id,
            correlation_id
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_evidence_record_signed_at
        ON platform.evidence_record (
            tenant_id,
            signed_at
        )
        """
    )

    op.execute(
        """
        ALTER TABLE platform.evidence_record
        ENABLE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        ALTER TABLE platform.evidence_record
        FORCE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        CREATE POLICY evidence_record_tenant_isolation
        ON platform.evidence_record
        USING (
            tenant_id = platform.current_tenant_id()
        )
        WITH CHECK (
            tenant_id = platform.current_tenant_id()
        )
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            platform.reject_evidence_record_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'platform.evidence_record is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER evidence_record_append_only
        BEFORE UPDATE OR DELETE
        ON platform.evidence_record
        FOR EACH ROW
        EXECUTE FUNCTION
            platform.reject_evidence_record_mutation()
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = 'coredata_runtime'
            ) THEN
                EXECUTE
                    'GRANT SELECT, INSERT ON '
                    'platform.evidence_record '
                    'TO coredata_runtime';

                EXECUTE
                    'REVOKE UPDATE, DELETE ON '
                    'platform.evidence_record '
                    'FROM coredata_runtime';
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.evidence_record IS
        'Tenant-scoped append-only cryptographic evidence'
        """
    )


def downgrade() -> None:
    # Phase 0 uses expand/migrate/contract.
    # Destructive downgrade is intentionally not automated.
    pass
