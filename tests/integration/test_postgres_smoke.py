from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import admin_url, provision_roles, run_alembic


async def _select_one(url: str) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return int(result.scalar_one())
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_postgresql_18_smoke_and_migration() -> None:
    with PostgresContainer("postgres:18") as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))
        run_alembic(migration_url, runtime_url)
        assert asyncio.run(_select_one(runtime_url)) == 1
