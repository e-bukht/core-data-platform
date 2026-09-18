from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_migrations_apply_on_supported_postgresql_matrix(image: str) -> None:
    with PostgresContainer(image) as postgres:
        sync_url = postgres.get_connection_url().replace("psycopg2", "psycopg")
        env = os.environ | {"CORE_PLATFORM_DATABASE_URL": sync_url}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[2],
            env=env,
            check=True,
        )
