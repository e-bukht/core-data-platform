from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer


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
        sync_url = postgres.get_connection_url().replace("psycopg2", "psycopg")
        async_url = sync_url.replace("postgresql://", "postgresql+psycopg://")
        env = os.environ | {"CORE_PLATFORM_DATABASE_URL": async_url}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[2],
            env=env,
            check=True,
        )
        assert asyncio.run(_select_one(async_url)) == 1
