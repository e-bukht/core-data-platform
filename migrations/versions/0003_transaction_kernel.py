"""Transaction Kernel persistence foundation.

Revision ID: 0003_transaction_kernel
Revises: 0002_context_trust
"""

from __future__ import annotations

from alembic import op

revision = "0003_transaction_kernel"
down_revision = "0002_context_trust"
branch_labels = None
depends_on = None

TENANT_SCOPED_TABLES = (
    "idempotency_record",
    "outbox_message",
    "inbox_message",
    "audit_record",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.idempotency_record (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id) ON DELETE RESTRICT,
            operation varchar(160) NOT NULL,
            idempotency_key varchar(255) NOT NULL,
            request_hash varchar(80) NOT NULL,
            status varchar(32) NOT NULL
                CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
            transaction_id uuid NOT NULL,
            result_reference varchar(500) NULL,
            response_status integer NULL
                CHECK (
                    response_status IS NULL
                    OR response_status BETWEEN 100 AND 599
                ),
            response_payload jsonb NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz NULL,
            expires_at timestamptz NOT NULL,

            CONSTRAINT uq_idempotency_record_key
                UNIQUE (tenant_id, operation, idempotency_key),

            CONSTRAINT ck_idempotency_record_lifetime
                CHECK (expires_at > created_at),

            CONSTRAINT ck_idempotency_record_completion
                CHECK (
                    (
                        status = 'IN_PROGRESS'
                        AND completed_at IS NULL
                    )
                    OR
                    (
                        status = 'COMPLETED'
                        AND completed_at IS NOT NULL
                    )
                ),

            CONSTRAINT ck_idempotency_record_operation
                CHECK (length(btrim(operation)) > 0),

            CONSTRAINT ck_idempotency_record_key
                CHECK (length(btrim(idempotency_key)) > 0),

            CONSTRAINT ck_idempotency_record_hash
                CHECK (length(btrim(request_hash)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE platform.outbox_message (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id) ON DELETE RESTRICT,
            transaction_id uuid NOT NULL,
            actor_id uuid NOT NULL
                REFERENCES platform.actor(id) ON DELETE RESTRICT,

            message_type varchar(240) NOT NULL,
            schema_version integer NOT NULL
                CHECK (schema_version > 0),
            source varchar(240) NOT NULL,

            occurred_at timestamptz NOT NULL,
            available_at timestamptz NOT NULL,
            published_at timestamptz NULL,

            correlation_id uuid NOT NULL,
            causation_id uuid NULL,

            aggregate_type varchar(160) NULL,
            aggregate_id varchar(255) NULL,
            aggregate_version bigint NULL
                CHECK (
                    aggregate_version IS NULL
                    OR aggregate_version >= 0
                ),

            payload jsonb NOT NULL,
            payload_hash varchar(80) NOT NULL,

            attempt_count integer NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),

            lease_owner varchar(200) NULL,
            lease_until timestamptz NULL,
            last_error text NULL,

            CONSTRAINT ck_outbox_message_type
                CHECK (length(btrim(message_type)) > 0),

            CONSTRAINT ck_outbox_message_source
                CHECK (length(btrim(source)) > 0),

            CONSTRAINT ck_outbox_message_hash
                CHECK (length(btrim(payload_hash)) > 0),

            CONSTRAINT ck_outbox_message_lease
                CHECK (
                    (lease_owner IS NULL AND lease_until IS NULL)
                    OR
                    (lease_owner IS NOT NULL AND lease_until IS NOT NULL)
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE platform.inbox_message (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id) ON DELETE RESTRICT,

            consumer_name varchar(200) NOT NULL,
            message_id uuid NOT NULL,
            message_type varchar(240) NOT NULL,

            correlation_id uuid NOT NULL,
            causation_id uuid NULL,
            payload_hash varchar(80) NOT NULL,

            received_at timestamptz NOT NULL,
            processed_at timestamptz NULL,

            CONSTRAINT uq_inbox_message_consumer
                UNIQUE (tenant_id, consumer_name, message_id),

            CONSTRAINT ck_inbox_message_consumer
                CHECK (length(btrim(consumer_name)) > 0),

            CONSTRAINT ck_inbox_message_type
                CHECK (length(btrim(message_type)) > 0),

            CONSTRAINT ck_inbox_message_hash
                CHECK (length(btrim(payload_hash)) > 0),

            CONSTRAINT ck_inbox_message_processing_time
                CHECK (
                    processed_at IS NULL
                    OR processed_at >= received_at
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE platform.audit_record (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id) ON DELETE RESTRICT,
            transaction_id uuid NOT NULL,
            actor_id uuid NOT NULL
                REFERENCES platform.actor(id) ON DELETE RESTRICT,
            correlation_id uuid NOT NULL,

            capability varchar(240) NOT NULL,
            action varchar(240) NOT NULL,
            resource_type varchar(160) NOT NULL,
            resource_id varchar(255) NULL,

            outcome varchar(32) NOT NULL
                CHECK (outcome IN ('SUCCESS', 'DENIED', 'FAILURE')),

            occurred_at timestamptz NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,

            CONSTRAINT ck_audit_record_capability
                CHECK (length(btrim(capability)) > 0),

            CONSTRAINT ck_audit_record_action
                CHECK (length(btrim(action)) > 0),

            CONSTRAINT ck_audit_record_resource_type
                CHECK (length(btrim(resource_type)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_idempotency_record_transaction
        ON platform.idempotency_record (tenant_id, transaction_id)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_idempotency_record_expiry
        ON platform.idempotency_record (tenant_id, expires_at)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_outbox_message_transaction
        ON platform.outbox_message (tenant_id, transaction_id)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_outbox_dispatch_ready
        ON platform.outbox_message (
            tenant_id,
            available_at,
            occurred_at
        )
        WHERE published_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX ix_outbox_message_lease
        ON platform.outbox_message (tenant_id, lease_until)
        WHERE published_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX ix_inbox_message_received
        ON platform.inbox_message (tenant_id, received_at)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_audit_record_transaction
        ON platform.audit_record (tenant_id, transaction_id)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_audit_record_correlation
        ON platform.audit_record (tenant_id, correlation_id)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_audit_record_occurred
        ON platform.audit_record (tenant_id, occurred_at)
        """
    )

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE platform.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation
            ON platform.{table}
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
        CREATE OR REPLACE FUNCTION platform.reject_audit_record_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'platform.audit_record is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER audit_record_append_only
        BEFORE UPDATE OR DELETE
        ON platform.audit_record
        FOR EACH ROW
        EXECUTE FUNCTION platform.reject_audit_record_mutation()
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
                    'GRANT SELECT, INSERT, UPDATE ON '
                    'platform.idempotency_record, '
                    'platform.outbox_message, '
                    'platform.inbox_message '
                    'TO coredata_runtime';

                EXECUTE
                    'GRANT SELECT, INSERT ON '
                    'platform.audit_record '
                    'TO coredata_runtime';

                EXECUTE
                    'REVOKE DELETE ON '
                    'platform.idempotency_record, '
                    'platform.outbox_message, '
                    'platform.inbox_message, '
                    'platform.audit_record '
                    'FROM coredata_runtime';

                EXECUTE
                    'REVOKE UPDATE ON '
                    'platform.audit_record '
                    'FROM coredata_runtime';
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.idempotency_record IS
        'Tenant-scoped command idempotency registry'
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.outbox_message IS
        'Transactional outbox with at-least-once delivery semantics'
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.inbox_message IS
        'Transactional consumer deduplication registry'
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.audit_record IS
        'Durable append-only transaction audit foundation'
        """
    )


def downgrade() -> None:
    # Phase 0 uses expand/migrate/contract.
    # Destructive downgrade is intentionally not automated.
    pass
