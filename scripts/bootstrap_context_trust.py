from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine, text

from core_platform.host.settings import get_settings

TENANT_ID = UUID("00000000-0000-7000-8000-000000000001")
ACTOR_ID = UUID("00000000-0000-7000-8000-000000000002")
IDENTITY_ID = UUID("00000000-0000-7000-8000-000000000003")
KEYCLOAK_ALICE_SUBJECT = "11111111-1111-4111-8111-111111111111"

CAPABILITIES = (
    "platform.context.read",
    "platform.tenant.read",
    "platform.actor.read.self",
    "platform.capability.read.self",
)


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.require_migration_database_url())
    now = datetime.now(UTC)
    issuer = settings.oidc_issuer.rstrip("/")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO platform.tenant(
                    id, code, display_name, status, created_at, updated_at
                )
                VALUES (:id, 'local', 'Local Development Tenant', 'ACTIVE', :now, :now)
                ON CONFLICT (id) DO UPDATE
                SET status = 'ACTIVE',
                    display_name = EXCLUDED.display_name,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {"id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO platform.actor(
                    id, actor_type, status, display_name, created_at, updated_at
                )
                VALUES (:id, 'HUMAN', 'ACTIVE', 'Alice Local', :now, :now)
                ON CONFLICT (id) DO UPDATE
                SET status = 'ACTIVE',
                    display_name = EXCLUDED.display_name,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {"id": ACTOR_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO platform.external_identity(
                    id, provider_type, issuer, subject, actor_id, status, metadata
                )
                VALUES (:id, 'OIDC', :issuer, :subject, :actor_id, 'ACTIVE', '{}'::jsonb)
                ON CONFLICT (issuer, subject) DO UPDATE
                SET actor_id = EXCLUDED.actor_id, status = 'ACTIVE'
                """
            ),
            {
                "id": IDENTITY_ID,
                "issuer": issuer,
                "subject": KEYCLOAK_ALICE_SUBJECT,
                "actor_id": ACTOR_ID,
            },
        )
        connection.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": str(TENANT_ID)},
        )
        connection.execute(
            text(
                """
                INSERT INTO platform.tenant_membership(
                    tenant_id, actor_id, status, valid_from, version
                )
                VALUES (:tenant_id, :actor_id, 'ACTIVE', :now, 0)
                ON CONFLICT (tenant_id, actor_id) DO UPDATE
                SET status = 'ACTIVE', valid_from = EXCLUDED.valid_from
                """
            ),
            {"tenant_id": TENANT_ID, "actor_id": ACTOR_ID, "now": now},
        )
        capability_rows = connection.execute(
            text(
                "SELECT id, code FROM platform.capability WHERE code = ANY(CAST(:codes AS text[]))"
            ),
            {"codes": list(CAPABILITIES)},
        ).mappings()
        for index, row in enumerate(capability_rows, start=1):
            grant_id = UUID(f"00000000-0000-7000-8000-{index:012d}")
            connection.execute(
                text(
                    """
                    INSERT INTO platform.capability_grant(
                        id, tenant_id, actor_id, capability_id, status, valid_from
                    )
                    VALUES (:id, :tenant_id, :actor_id, :capability_id, 'ACTIVE', :now)
                    ON CONFLICT (tenant_id, actor_id, capability_id) DO UPDATE
                    SET status = 'ACTIVE', valid_from = EXCLUDED.valid_from
                    """
                ),
                {
                    "id": grant_id,
                    "tenant_id": TENANT_ID,
                    "actor_id": ACTOR_ID,
                    "capability_id": row["id"],
                    "now": now,
                },
            )
    engine.dispose()
    print(f"Context & Trust local fixture ready. Tenant ID: {TENANT_ID}")


if __name__ == "__main__":
    main()
