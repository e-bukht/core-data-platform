from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = UUID("00000000-0000-7300-8000-000000001301")
ACTOR_ID = UUID("00000000-0000-7300-8000-000000001302")

TRANSACTION_TABLES = (
    "idempotency_record",
    "outbox_message",
    "inbox_message",
    "audit_record",
)


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_p0_i2_upgrades_exactly_to_p0_i3(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        original_url = admin_url(postgres)

        migration_url, runtime_url = provision_roles(original_url)

        # Establish an actual certified P0-I2 schema boundary.
        run_alembic(
            migration_url,
            runtime_url,
            "0002_context_trust",
        )

        engine = create_engine(migration_url)

        try:
            with engine.begin() as connection:
                revision = connection.scalar(
                    text(
                        """
                        SELECT version_num
                        FROM alembic_version
                        """
                    )
                )

                assert revision == "0002_context_trust"

                for table in TRANSACTION_TABLES:
                    relation = connection.scalar(
                        text(
                            """
                            SELECT to_regclass(
                                :qualified_name
                            )
                            """
                        ),
                        {"qualified_name": (f"platform.{table}")},
                    )

                    assert relation is None

                # Representative pre-existing P0-I2 data.
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant (
                            id,
                            code,
                            display_name,
                            status
                        )
                        VALUES (
                            CAST(:tenant_id AS uuid),
                            'p0-i2-upgrade',
                            'P0-I2 Upgrade Tenant',
                            'ACTIVE'
                        )
                        """
                    ),
                    {"tenant_id": str(TENANT_ID)},
                )

                connection.execute(
                    text(
                        """
                        INSERT INTO platform.actor (
                            id,
                            actor_type,
                            status,
                            display_name
                        )
                        VALUES (
                            CAST(:actor_id AS uuid),
                            'SERVICE',
                            'ACTIVE',
                            'P0-I2 Upgrade Actor'
                        )
                        """
                    ),
                    {"actor_id": str(ACTOR_ID)},
                )
        finally:
            engine.dispose()

        # Execute exactly the P0-I2 -> P0-I3 migration.
        run_alembic(
            migration_url,
            runtime_url,
            "0003_transaction_kernel",
        )

        engine = create_engine(migration_url)

        try:
            with engine.connect() as connection:
                revision = connection.scalar(
                    text(
                        """
                        SELECT version_num
                        FROM alembic_version
                        """
                    )
                )

                assert revision == "0003_transaction_kernel"

                tenant = connection.scalar(
                    text(
                        """
                        SELECT code
                        FROM platform.tenant
                        WHERE id =
                            CAST(:tenant_id AS uuid)
                        """
                    ),
                    {"tenant_id": str(TENANT_ID)},
                )

                actor = connection.scalar(
                    text(
                        """
                        SELECT display_name
                        FROM platform.actor
                        WHERE id =
                            CAST(:actor_id AS uuid)
                        """
                    ),
                    {"actor_id": str(ACTOR_ID)},
                )

                assert tenant == "p0-i2-upgrade"
                assert actor == "P0-I2 Upgrade Actor"

                for table in TRANSACTION_TABLES:
                    relation = connection.scalar(
                        text(
                            """
                            SELECT to_regclass(
                                :qualified_name
                            )
                            """
                        ),
                        {"qualified_name": (f"platform.{table}")},
                    )

                    assert relation is not None
        finally:
            engine.dispose()
