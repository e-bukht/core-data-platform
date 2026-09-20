from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from core_platform.infrastructure.persistence.database import Database
from tests.integration.db_support import (
    RUNTIME_ROLE,
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_A = UUID("00000000-0000-7000-8000-000000000011")
TENANT_B = UUID("00000000-0000-7000-8000-000000000012")
ACTOR_A = UUID("00000000-0000-7000-8000-000000000021")
ACTOR_B = UUID("00000000-0000-7000-8000-000000000022")


def _seed(migration_url: str) -> None:
    engine = create_engine(migration_url)
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            for tenant_id, code in ((TENANT_A, "tenant-a"), (TENANT_B, "tenant-b")):
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant(
                            id, code, display_name, status, created_at, updated_at
                        )
                        VALUES (:id, :code, :code, 'ACTIVE', :now, :now)
                        """
                    ),
                    {"id": tenant_id, "code": code, "now": now},
                )
            for actor_id, name in ((ACTOR_A, "actor-a"), (ACTOR_B, "actor-b")):
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.actor(
                            id, actor_type, status, display_name, created_at, updated_at
                        )
                        VALUES (:id, 'HUMAN', 'ACTIVE', :name, :now, :now)
                        """
                    ),
                    {"id": actor_id, "name": name, "now": now},
                )
            for tenant_id, actor_id in (
                (TENANT_A, ACTOR_A),
                (TENANT_B, ACTOR_B),
            ):
                connection.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant_membership(
                            tenant_id, actor_id, status, valid_from, version
                        )
                        VALUES (:tenant_id, :actor_id, 'ACTIVE', :now, 0)
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "actor_id": actor_id,
                        "now": now,
                    },
                )
    finally:
        engine.dispose()


async def _rls_assertions(runtime_url: str) -> None:
    database = Database(runtime_url, pool_size=1, max_overflow=0)
    try:
        async with database.transaction() as connection:
            rows = (
                (await connection.execute(text("SELECT tenant_id FROM platform.tenant_membership")))
                .scalars()
                .all()
            )
            assert rows == []

        async with database.tenant_transaction(TENANT_A) as connection:
            rows = (
                (
                    await connection.execute(
                        text("SELECT tenant_id FROM platform.tenant_membership ORDER BY tenant_id")
                    )
                )
                .scalars()
                .all()
            )
            assert rows == [TENANT_A]

        async with database.tenant_transaction(TENANT_B) as connection:
            rows = (
                (
                    await connection.execute(
                        text("SELECT tenant_id FROM platform.tenant_membership ORDER BY tenant_id")
                    )
                )
                .scalars()
                .all()
            )
            assert rows == [TENANT_B]

        with pytest.raises(DBAPIError):
            async with database.tenant_transaction(TENANT_A) as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO platform.tenant_membership(
                            tenant_id, actor_id, status, valid_from, version
                        ) VALUES (:tenant_b, :actor_a, 'ACTIVE', now(), 0)
                        """
                    ),
                    {"tenant_b": TENANT_B, "actor_a": ACTOR_A},
                )
    finally:
        await database.close()


def _role_assertions(admin_database_url: str) -> None:
    engine = create_engine(admin_database_url)
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    """
                    SELECT rolsuper, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = :role
                    """
                ),
                {"role": RUNTIME_ROLE},
            ).one()
            assert role.rolsuper is False
            assert role.rolbypassrls is False
            table_rows = list(
                connection.execute(
                    text(
                        """
                        SELECT c.relname, r.rolname AS owner, c.relrowsecurity,
                        c.relforcerowsecurity
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        JOIN pg_roles r ON r.oid = c.relowner
                        WHERE n.nspname = 'platform'
                          AND c.relname IN ('tenant_membership', 'capability_grant')
                        ORDER BY c.relname
                        """
                    )
                ).mappings()
            )
            assert {row["relname"] for row in table_rows} == {
                "tenant_membership",
                "capability_grant",
            }
            assert all(row["owner"] != RUNTIME_ROLE for row in table_rows)
            assert all(row["relforcerowsecurity"] is True for row in table_rows)
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_rls_and_runtime_role_isolation(image: str) -> None:
    with PostgresContainer(image) as postgres:
        admin_database_url = admin_url(postgres)
        migration_url, runtime_url = provision_roles(admin_database_url)
        run_alembic(migration_url, runtime_url)
        _seed(migration_url)
        asyncio.run(_rls_assertions(runtime_url))
        _role_assertions(admin_database_url)
