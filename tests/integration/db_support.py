from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).parents[2]


class PostgresContainerLike(Protocol):
    def get_connection_url(self) -> str: ...


MIGRATOR_ROLE = "coredata_migrator"
MIGRATOR_PASSWORD = "test-migrator-only"
RUNTIME_ROLE = "coredata_runtime"
RUNTIME_PASSWORD = "test-runtime-only"


def admin_url(postgres: PostgresContainerLike) -> str:
    raw = postgres.get_connection_url()
    return raw.replace("psycopg2", "psycopg")


def provision_roles(admin_database_url: str) -> tuple[str, str]:
    parsed = make_url(admin_database_url)
    if parsed.host is None or parsed.port is None or parsed.database is None:
        raise RuntimeError("Unexpected Testcontainers PostgreSQL URL")

    engine = create_engine(admin_database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = '{MIGRATOR_ROLE}'
                        ) THEN
                            CREATE ROLE {MIGRATOR_ROLE} LOGIN PASSWORD '{MIGRATOR_PASSWORD}'
                                NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
                            CREATE ROLE {RUNTIME_ROLE} LOGIN PASSWORD '{RUNTIME_PASSWORD}'
                                NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
                        END IF;
                    END
                    $$
                    """
                )
            )
            connection.execute(text(f'ALTER DATABASE "{parsed.database}" OWNER TO {MIGRATOR_ROLE}'))
            schema_exists = connection.execute(
                text("SELECT to_regnamespace('platform')")
            ).scalar_one()
            if schema_exists is not None:
                connection.execute(text(f"ALTER SCHEMA platform OWNER TO {MIGRATOR_ROLE}"))
            alembic_exists = connection.execute(
                text("SELECT to_regclass('public.alembic_version')")
            ).scalar_one()
            if alembic_exists is not None:
                connection.execute(
                    text(f"ALTER TABLE public.alembic_version OWNER TO {MIGRATOR_ROLE}")
                )
    finally:
        engine.dispose()

    host = parsed.host
    database = parsed.database
    migration_url = (
        f"postgresql+psycopg://{MIGRATOR_ROLE}:{quote(MIGRATOR_PASSWORD)}"
        f"@{host}:{parsed.port}/{database}"
    )
    runtime_url = (
        f"postgresql+psycopg://{RUNTIME_ROLE}:{quote(RUNTIME_PASSWORD)}"
        f"@{host}:{parsed.port}/{database}"
    )
    return migration_url, runtime_url


def run_alembic(migration_url: str, runtime_url: str, target: str = "head") -> None:
    env = os.environ | {
        "CORE_PLATFORM_MIGRATION_DATABASE_URL": migration_url,
        "CORE_PLATFORM_DATABASE_URL": runtime_url,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=ROOT,
        env=env,
        check=True,
    )
