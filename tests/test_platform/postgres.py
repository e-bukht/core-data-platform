from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from testcontainers.community.postgres import PostgresContainer

from core_platform.infrastructure.persistence.database import Database
from tests.integration.db_support import admin_url, provision_roles, run_alembic


@dataclass(frozen=True, slots=True)
class CertificationPostgres:
    """Migrated PostgreSQL runtime for reusable certification scenarios."""

    image: str
    admin_database_url: str
    migration_url: str
    runtime_url: str
    database: Database


@pytest.fixture
def cert_postgres(
    request: pytest.FixtureRequest,
) -> Iterator[CertificationPostgres]:
    image = getattr(request, "param", "postgres:18")

    if not isinstance(image, str):
        raise TypeError("cert_postgres indirect parameter MUST be a PostgreSQL image string")

    with PostgresContainer(image) as postgres:
        admin_database_url = admin_url(postgres)
        migration_url, runtime_url = provision_roles(admin_database_url)

        run_alembic(
            migration_url,
            runtime_url,
        )

        database = Database(
            runtime_url,
            pool_size=1,
            max_overflow=0,
        )

        try:
            yield CertificationPostgres(
                image=image,
                admin_database_url=admin_database_url,
                migration_url=migration_url,
                runtime_url=runtime_url,
                database=database,
            )
        finally:
            asyncio.run(database.close())