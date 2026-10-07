from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.test_platform.assertions import (
    assert_cross_tenant_denied,
)
from tests.test_platform.postgres import CertificationPostgres

TENANT_A = UUID("00000000-0000-7000-8000-00000000c501")
TENANT_B = UUID("00000000-0000-7000-8000-00000000c502")
ACTOR_A = UUID("00000000-0000-7000-8000-00000000c503")
ACTOR_B = UUID("00000000-0000-7000-8000-00000000c504")

NOW = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


def _seed(
    postgres: CertificationPostgres,
) -> None:
    engine = create_engine(postgres.migration_url)

    try:
        with engine.begin() as connection:
            for tenant_id, code in (
                (TENANT_A, "certification-tenant-a"),
                (TENANT_B, "certification-tenant-b"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant(
                            id,
                            code,
                            display_name,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :id,
                            :code,
                            :code,
                            'ACTIVE',
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "id": tenant_id,
                        "code": code,
                        "now": NOW,
                    },
                )

            for actor_id, name in (
                (ACTOR_A, "Certification Actor A"),
                (ACTOR_B, "Certification Actor B"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.actor(
                            id,
                            actor_type,
                            status,
                            display_name,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :id,
                            'HUMAN',
                            'ACTIVE',
                            :name,
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "id": actor_id,
                        "name": name,
                        "now": NOW,
                    },
                )

            for tenant_id, actor_id in (
                (TENANT_A, ACTOR_A),
                (TENANT_B, ACTOR_B),
            ):
                connection.execute(
                    text(
                        """
                        SELECT set_config(
                            'app.current_tenant_id',
                            :tenant_id,
                            true
                        )
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                    },
                )

                connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant_membership(
                            tenant_id,
                            actor_id,
                            status,
                            valid_from,
                            version
                        )
                        VALUES (
                            :tenant_id,
                            :actor_id,
                            'ACTIVE',
                            :now,
                            0
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "actor_id": actor_id,
                        "now": NOW,
                    },
                )
    finally:
        engine.dispose()


async def _cross_tenant_insert(
    connection: AsyncConnection,
) -> object:
    return await connection.execute(
        text(
            """
            INSERT INTO platform.tenant_membership(
                tenant_id,
                actor_id,
                status,
                valid_from,
                version
            )
            VALUES (
                :tenant_id,
                :actor_id,
                'ACTIVE',
                :now,
                0
            )
            """
        ),
        {
            "tenant_id": TENANT_B,
            "actor_id": ACTOR_A,
            "now": NOW,
        },
    )


async def _assert_isolation(
    postgres: CertificationPostgres,
) -> None:
    async with postgres.database.tenant_transaction(TENANT_A) as connection:
        tenants = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT tenant_id
                        FROM platform.tenant_membership
                        ORDER BY tenant_id
                        """
                    )
                )
            )
            .scalars()
            .all()
        )

    assert tenants == [TENANT_A]

    await assert_cross_tenant_denied(
        postgres.database,
        TENANT_A,
        _cross_tenant_insert,
    )

    async with postgres.database.tenant_transaction(TENANT_B) as connection:
        actors = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT actor_id
                        FROM platform.tenant_membership
                        ORDER BY actor_id
                        """
                    )
                )
            )
            .scalars()
            .all()
        )

    assert actors == [ACTOR_B]


@pytest.mark.integration
def test_reusable_cross_tenant_denial_assertion(
    cert_postgres: CertificationPostgres,
) -> None:
    _seed(cert_postgres)

    asyncio.run(
        _assert_isolation(
            cert_postgres
        )
    )