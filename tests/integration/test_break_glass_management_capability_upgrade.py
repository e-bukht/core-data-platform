from __future__ import annotations

from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

CAPABILITY_ID = (
    "00000000-0000-7000-8000-000000000105"
)
CAPABILITY_CODE = "platform.break-glass.manage"
EXPECTED_REVISION = (
    "0006_bg_manage_capability"
)


def _assert_capability_absent(
    migration_url: str,
) -> None:
    engine = create_engine(
        migration_url
    )

    try:
        with engine.connect() as connection:
            count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform.capability
                    WHERE code = :code
                    """
                ),
                {
                    "code": CAPABILITY_CODE,
                },
            ).scalar_one()

            assert count == 0
    finally:
        engine.dispose()


def _assert_capability_registered(
    migration_url: str,
) -> None:
    engine = create_engine(
        migration_url
    )

    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text(
                    """
                    SELECT version_num
                    FROM alembic_version
                    """
                )
            ).scalar_one()

            capability = (
                connection.execute(
                    text(
                        """
                        SELECT
                            id::text AS id,
                            code,
                            description,
                            risk_class,
                            status
                        FROM platform.capability
                        WHERE code = :code
                        """
                    ),
                    {
                        "code": CAPABILITY_CODE,
                    },
                )
                .mappings()
                .one()
            )

            grant_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform.capability_grant AS grant_row
                    JOIN platform.capability AS capability_row
                      ON capability_row.id =
                         grant_row.capability_id
                    WHERE capability_row.code = :code
                    """
                ),
                {
                    "code": CAPABILITY_CODE,
                },
            ).scalar_one()

            assert revision == EXPECTED_REVISION
            assert capability["id"] == CAPABILITY_ID
            assert capability["code"] == CAPABILITY_CODE
            assert capability["description"] == (
                "Manage tenant-scoped break-glass grants"
            )
            assert capability["risk_class"] == "CRITICAL"
            assert capability["status"] == "ACTIVE"

            # Catalog registration must never grant authority
            # implicitly to any actor or tenant.
            assert grant_count == 0
    finally:
        engine.dispose()


def _exercise_upgrade(
    image: str,
) -> None:
    with PostgresContainer(
        image
    ) as postgres:
        migration_url, runtime_url = (
            provision_roles(
                admin_url(postgres)
            )
        )

        run_alembic(
            migration_url,
            runtime_url,
            "0005_break_glass",
        )

        _assert_capability_absent(
            migration_url
        )

        run_alembic(
            migration_url,
            runtime_url,
            "head",
        )

        _assert_capability_registered(
            migration_url
        )


def test_break_glass_management_capability_upgrade_postgres_12() -> None:
    _exercise_upgrade(
        "postgres:12.22"
    )


def test_break_glass_management_capability_upgrade_postgres_18() -> None:
    _exercise_upgrade(
        "postgres:18"
    )
