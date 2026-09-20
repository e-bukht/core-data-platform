"""Context and Trust kernel with tenant isolation.

Revision ID: 0002_context_trust
Revises: 0001_bootstrap_platform
"""

from __future__ import annotations

from alembic import op

revision = "0002_context_trust"
down_revision = "0001_bootstrap_platform"
branch_labels = None
depends_on = None


CAPABILITIES = (
    (
        "00000000-0000-7000-8000-000000000101",
        "platform.context.read",
        "Read the current execution context diagnostic",
        "LOW",
    ),
    (
        "00000000-0000-7000-8000-000000000102",
        "platform.tenant.read",
        "Read the current tenant context",
        "LOW",
    ),
    (
        "00000000-0000-7000-8000-000000000103",
        "platform.actor.read.self",
        "Read the current actor context",
        "LOW",
    ),
    (
        "00000000-0000-7000-8000-000000000104",
        "platform.capability.read.self",
        "List the current actor effective capabilities",
        "LOW",
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.tenant (
            id uuid PRIMARY KEY,
            code varchar(80) NOT NULL UNIQUE,
            display_name varchar(200) NOT NULL,
            status varchar(32) NOT NULL CHECK (
                status IN ('PROVISIONING','ACTIVE','SUSPENDED','TERMINATING','ARCHIVED')
            ),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.actor (
            id uuid PRIMARY KEY,
            actor_type varchar(32) NOT NULL CHECK (
                actor_type IN ('HUMAN','AGENT','SERVICE','INTEGRATION','SYSTEM')
            ),
            status varchar(32) NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','REVOKED')),
            display_name varchar(200) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.external_identity (
            id uuid PRIMARY KEY,
            provider_type varchar(32) NOT NULL CHECK (provider_type = 'OIDC'),
            issuer varchar(500) NOT NULL,
            subject varchar(255) NOT NULL,
            actor_id uuid NOT NULL REFERENCES platform.actor(id) ON DELETE RESTRICT,
            status varchar(32) NOT NULL CHECK (status IN ('ACTIVE','REVOKED')),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT uq_external_identity_issuer_subject UNIQUE (issuer, subject)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.tenant_membership (
            tenant_id uuid NOT NULL REFERENCES platform.tenant(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES platform.actor(id) ON DELETE RESTRICT,
            status varchar(32) NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','REVOKED')),
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_until timestamptz NULL,
            version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
            PRIMARY KEY (tenant_id, actor_id),
            CHECK (valid_until IS NULL OR valid_until > valid_from)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.capability (
            id uuid PRIMARY KEY,
            code varchar(160) NOT NULL UNIQUE,
            description varchar(500) NOT NULL,
            risk_class varchar(32) NOT NULL CHECK (
                risk_class IN ('LOW','MEDIUM','HIGH','CRITICAL')
            ),
            status varchar(32) NOT NULL CHECK (status IN ('ACTIVE','RETIRED'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.capability_grant (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES platform.tenant(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES platform.actor(id) ON DELETE RESTRICT,
            capability_id uuid NOT NULL REFERENCES platform.capability(id) ON DELETE RESTRICT,
            status varchar(32) NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','REVOKED')),
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_until timestamptz NULL,
            CONSTRAINT uq_capability_grant_subject_capability
                UNIQUE (tenant_id, actor_id, capability_id),
            CHECK (valid_until IS NULL OR valid_until > valid_from)
        )
        """
    )
    op.execute("CREATE INDEX ix_external_identity_actor_id ON platform.external_identity(actor_id)")
    op.execute(
        "CREATE INDEX ix_capability_grant_subject ON platform.capability_grant(tenant_id, actor_id)"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform.current_tenant_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        $$
        """
    )

    for table in ("tenant_membership", "capability_grant"):
        op.execute(f"ALTER TABLE platform.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation
            ON platform.{table}
            USING (tenant_id = platform.current_tenant_id())
            WITH CHECK (tenant_id = platform.current_tenant_id())
            """
        )

    for capability_id, code, description, risk_class in CAPABILITIES:
        escaped_description = description.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO platform.capability(id, code, description, risk_class, status)
            VALUES (
                '{capability_id}'::uuid,
                '{code}',
                '{escaped_description}',
                '{risk_class}',
                'ACTIVE'
            )
            ON CONFLICT (code) DO NOTHING
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'coredata_runtime') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA platform TO coredata_runtime';
                EXECUTE 'GRANT SELECT ON platform.tenant, platform.actor, '
                    'platform.external_identity, platform.capability TO coredata_runtime';
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON '
                    'platform.tenant_membership, platform.capability_grant TO coredata_runtime';
                EXECUTE 'GRANT SELECT ON public.alembic_version TO coredata_runtime';
            END IF;
        END
        $$
        """
    )

    op.execute("COMMENT ON TABLE platform.tenant IS 'Platform tenant isolation boundary'")
    op.execute("COMMENT ON TABLE platform.actor IS 'Generic execution actor, distinct from Party'")
    op.execute(
        "COMMENT ON FUNCTION platform.current_tenant_id() IS "
        "'Transaction-local tenant context used by RLS policies'"
    )


def downgrade() -> None:
    # P0 follows expand/migrate/contract. Destructive downgrade is intentionally not automated.
    pass
