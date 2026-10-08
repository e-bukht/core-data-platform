from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from core_platform.infrastructure.persistence.schema import (
    EXPECTED_ALEMBIC_REVISION,
)
from tests.test_platform.postgres import CertificationPostgres


async def _runtime_identity(
    postgres: CertificationPostgres,
) -> tuple[str, str]:
    async with postgres.database.open_connection() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT
                        current_user,
                        (
                            SELECT version_num
                            FROM public.alembic_version
                            LIMIT 1
                        )
                    """
                )
            )
        ).one()

    return str(row[0]), str(row[1])


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "cert_postgres",
    [
        "postgres:12.22",
        "postgres:18",
    ],
    indirect=True,
)
def test_certification_postgres_fixture_is_migrated_and_runtime_scoped(
    cert_postgres: CertificationPostgres,
) -> None:
    readiness = asyncio.run(cert_postgres.database.readiness())

    assert readiness.ready
    assert readiness.revision == EXPECTED_ALEMBIC_REVISION

    current_user, revision = asyncio.run(_runtime_identity(cert_postgres))

    assert current_user == "coredata_runtime"
    assert revision == EXPECTED_ALEMBIC_REVISION
