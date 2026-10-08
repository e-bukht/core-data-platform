"""Tenant-scoped break-glass authorization grants.

Revision ID: 0005_break_glass
Revises: 0004_evidence
"""

from __future__ import annotations

from alembic import op

revision = "0005_break_glass"
down_revision = "0004_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.break_glass_grant (
            id uuid PRIMARY KEY,

            tenant_id uuid NOT NULL
                REFERENCES platform.tenant(id)
                ON DELETE RESTRICT,

            actor_id uuid NOT NULL
                REFERENCES platform.actor(id)
                ON DELETE RESTRICT,

            issued_by_actor_id uuid NOT NULL
                REFERENCES platform.actor(id)
                ON DELETE RESTRICT,

            capabilities varchar(160)[] NOT NULL
                CHECK (cardinality(capabilities) > 0),

            scope_kind varchar(32) NOT NULL
                CHECK (
                    scope_kind IN (
                        'TENANT',
                        'RESOURCE_TYPE',
                        'RESOURCE'
                    )
                ),

            resource_type varchar(160) NULL,
            resource_id varchar(255) NULL,

            reason varchar(2000) NOT NULL
                CHECK (length(btrim(reason)) > 0),

            valid_from timestamptz NOT NULL,
            valid_until timestamptz NOT NULL
                CHECK (valid_until > valid_from),

            status varchar(32) NOT NULL
                CHECK (
                    status IN (
                        'ACTIVE',
                        'SUSPENDED',
                        'REVOKED'
                    )
                ),

            accepted_acr_values varchar(255)[] NOT NULL,
            required_amr varchar(128)[] NOT NULL,

            version bigint NOT NULL DEFAULT 0
                CHECK (version >= 0),

            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT ck_break_glass_grant_scope
                CHECK (
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
                ),

            CONSTRAINT ck_break_glass_grant_assurance
                CHECK (
                    cardinality(accepted_acr_values) > 0
                    OR cardinality(required_amr) > 0
                )
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_break_glass_grant_subject
        ON platform.break_glass_grant (
            tenant_id,
            actor_id,
            status
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_break_glass_grant_expiry
        ON platform.break_glass_grant (
            tenant_id,
            valid_until
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_break_glass_grant_issuer
        ON platform.break_glass_grant (
            tenant_id,
            issued_by_actor_id
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_break_glass_grant_capabilities
        ON platform.break_glass_grant
        USING gin (capabilities)
        """
    )

    op.execute(
        """
        ALTER TABLE platform.break_glass_grant
        ENABLE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        ALTER TABLE platform.break_glass_grant
        FORCE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        CREATE POLICY break_glass_grant_tenant_isolation
        ON platform.break_glass_grant
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
            platform.guard_break_glass_grant_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'platform.break_glass_grant cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;

            IF ROW(
                NEW.id,
                NEW.tenant_id,
                NEW.actor_id,
                NEW.issued_by_actor_id,
                NEW.capabilities,
                NEW.scope_kind,
                NEW.resource_type,
                NEW.resource_id,
                NEW.reason,
                NEW.valid_from,
                NEW.valid_until,
                NEW.accepted_acr_values,
                NEW.required_amr,
                NEW.created_at
            )
            IS DISTINCT FROM
            ROW(
                OLD.id,
                OLD.tenant_id,
                OLD.actor_id,
                OLD.issued_by_actor_id,
                OLD.capabilities,
                OLD.scope_kind,
                OLD.resource_type,
                OLD.resource_id,
                OLD.reason,
                OLD.valid_from,
                OLD.valid_until,
                OLD.accepted_acr_values,
                OLD.required_amr,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION
                    'break-glass authorization surface is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF (
                OLD.status = 'REVOKED'
                AND NEW.status <> 'REVOKED'
            ) THEN
                RAISE EXCEPTION
                    'revoked break-glass grant is terminal'
                    USING ERRCODE = '55000';
            END IF;

            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION
                    'break-glass version must increment by one'
                    USING ERRCODE = '40001';
            END IF;

            IF NEW.updated_at < OLD.updated_at THEN
                RAISE EXCEPTION
                    'break-glass updated_at cannot move backwards'
                    USING ERRCODE = '55000';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER break_glass_grant_guard
        BEFORE UPDATE OR DELETE
        ON platform.break_glass_grant
        FOR EACH ROW
        EXECUTE FUNCTION
            platform.guard_break_glass_grant_mutation()
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
                    'platform.break_glass_grant '
                    'TO coredata_runtime';

                EXECUTE
                    'REVOKE UPDATE, DELETE ON '
                    'platform.break_glass_grant '
                    'FROM coredata_runtime';

                EXECUTE
                    'GRANT UPDATE '
                    '(status, version, updated_at) ON '
                    'platform.break_glass_grant '
                    'TO coredata_runtime';
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        COMMENT ON TABLE platform.break_glass_grant IS
        'Tenant-scoped, bounded emergency authorization grants'
        """
    )


def downgrade() -> None:
    # Phase 0 uses expand/migrate/contract.
    # Destructive downgrade is intentionally not automated.
    pass
