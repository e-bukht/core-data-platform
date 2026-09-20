from __future__ import annotations

import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import admin_url, provision_roles, run_alembic


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_migrations_apply_on_supported_postgresql_matrix(image: str) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))
        run_alembic(migration_url, runtime_url)


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_existing_p0_i1_database_upgrades_to_p0_i2(image: str) -> None:
    with PostgresContainer(image) as postgres:
        original_owner_url = admin_url(postgres)
        # Simulate the certified P0-I1 state: revision 0001 was applied by the
        # original database owner before dedicated P0-I2 roles existed.
        run_alembic(original_owner_url, original_owner_url, "0001_bootstrap_platform")
        migration_url, runtime_url = provision_roles(original_owner_url)
        run_alembic(migration_url, runtime_url, "head")
