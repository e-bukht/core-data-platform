from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import (
    RUNTIME_ROLE,
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_A = "00000000-0000-7600-8000-000000001001"
TENANT_B = "00000000-0000-7600-8000-000000001002"

ACTOR_A = "00000000-0000-7600-8000-000000001011"
ACTOR_B = "00000000-0000-7600-8000-000000001012"

ISSUER_A = "00000000-0000-7600-8000-000000001021"
ISSUER_B = "00000000-0000-7600-8000-000000001022"

GRANT_A = "00000000-0000-7600-8000-000000001031"
GRANT_B = "00000000-0000-7600-8000-000000001032"


def _set_tenant(
    connection: Connection,
    tenant_id: str,
) -> None:
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
        {"tenant_id": tenant_id},
    )


def _seed_context(engine: Engine) -> None:
    with engine.begin() as connection:
        for tenant_id, code in (
            (TENANT_A, "break-glass-a"),
            (TENANT_B, "break-glass-b"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO platform.tenant (
                        id,
                        code,
                        display_name,
                        status
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        :code,
                        :code,
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "code": code,
                },
            )

        for actor_id, name in (
            (ACTOR_A, "Break Glass Actor A"),
            (ACTOR_B, "Break Glass Actor B"),
            (ISSUER_A, "Break Glass Issuer A"),
            (ISSUER_B, "Break Glass Issuer B"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor (
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'HUMAN',
                        'ACTIVE',
                        :name
                    )
                    """
                ),
                {
                    "actor_id": actor_id,
                    "name": name,
                },
            )


def _insert_grant(
    connection: Connection,
    *,
    grant_id: str,
    tenant_id: str,
    actor_id: str,
    issuer_id: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO platform.break_glass_grant (
                id,
                tenant_id,
                actor_id,
                issued_by_actor_id,
                capabilities,
                scope_kind,
                resource_type,
                resource_id,
                reason,
                valid_from,
                valid_until,
                status,
                accepted_acr_values,
                required_amr
            )
            VALUES (
                CAST(:grant_id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:actor_id AS uuid),
                CAST(:issuer_id AS uuid),
                ARRAY[
                    'platform.outbox.retry'
                ]::varchar(160)[],
                'TENANT',
                NULL,
                NULL,
                'Emergency operational recovery',
                now() - interval '5 minutes',
                now() + interval '25 minutes',
                'ACTIVE',
                ARRAY[
                    'urn:core-platform:acr:elevated'
                ]::varchar(255)[],
                ARRAY[
                    'mfa'
                ]::varchar(128)[]
            )
            """
        ),
        {
            "grant_id": grant_id,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "issuer_id": issuer_id,
        },
    )


@contextmanager
def _engines(
    image: str,
) -> Iterator[tuple[Engine, Engine]]:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))

        run_alembic(
            migration_url,
            runtime_url,
        )

        migration_engine = create_engine(migration_url)
        runtime_engine = create_engine(runtime_url)

        try:
            yield migration_engine, runtime_engine
        finally:
            runtime_engine.dispose()
            migration_engine.dispose()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_break_glass_schema_is_tenant_safe_and_guarded(
    image: str,
) -> None:
    with _engines(image) as (
        migration_engine,
        runtime_engine,
    ):
        _seed_context(migration_engine)

        with migration_engine.connect() as connection:
            table_state = (
                connection.execute(
                    text(
                        """
                        SELECT
                            owner.rolname AS owner,
                            relation.relrowsecurity,
                            relation.relforcerowsecurity
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                            ON namespace.oid =
                                relation.relnamespace
                        JOIN pg_roles AS owner
                            ON owner.oid =
                                relation.relowner
                        WHERE namespace.nspname = 'platform'
                          AND relation.relname =
                              'break_glass_grant'
                        """
                    )
                )
                .mappings()
                .one()
            )

            table_privileges = (
                connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'SELECT'
                            ) AS can_select,
                            has_table_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'INSERT'
                            ) AS can_insert,
                            has_table_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'DELETE'
                            ) AS can_delete
                        """
                    ),
                    {
                        "runtime_role": RUNTIME_ROLE,
                    },
                )
                .mappings()
                .one()
            )

            column_privileges = (
                connection.execute(
                    text(
                        """
                        SELECT
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'status',
                                'UPDATE'
                            ) AS status_update,
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'version',
                                'UPDATE'
                            ) AS version_update,
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'updated_at',
                                'UPDATE'
                            ) AS updated_at_update,
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'capabilities',
                                'UPDATE'
                            ) AS capabilities_update,
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'scope_kind',
                                'UPDATE'
                            ) AS scope_update,
                            has_column_privilege(
                                :runtime_role,
                                'platform.break_glass_grant',
                                'valid_until',
                                'UPDATE'
                            ) AS validity_update
                        """
                    ),
                    {
                        "runtime_role": RUNTIME_ROLE,
                    },
                )
                .mappings()
                .one()
            )

        assert table_state["owner"] != RUNTIME_ROLE
        assert table_state["relrowsecurity"] is True
        assert table_state["relforcerowsecurity"] is True

        assert table_privileges["can_select"] is True
        assert table_privileges["can_insert"] is True
        assert table_privileges["can_delete"] is False

        assert column_privileges["status_update"] is True
        assert column_privileges["version_update"] is True
        assert column_privileges["updated_at_update"] is True
        assert column_privileges["capabilities_update"] is False
        assert column_privileges["scope_update"] is False
        assert column_privileges["validity_update"] is False

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )
            _insert_grant(
                connection,
                grant_id=GRANT_A,
                tenant_id=TENANT_A,
                actor_id=ACTOR_A,
                issuer_id=ISSUER_A,
            )

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_B,
            )
            _insert_grant(
                connection,
                grant_id=GRANT_B,
                tenant_id=TENANT_B,
                actor_id=ACTOR_B,
                issuer_id=ISSUER_B,
            )

        with runtime_engine.connect() as connection:
            count = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM platform.break_glass_grant
                    """
                )
            )

        assert count == 0

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            visible = set(
                connection.execute(
                    text(
                        """
                        SELECT id
                        FROM platform.break_glass_grant
                        """
                    )
                ).scalars()
            )

        assert {str(value) for value in visible} == {GRANT_A}

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_B,
            )

            visible = set(
                connection.execute(
                    text(
                        """
                        SELECT id
                        FROM platform.break_glass_grant
                        """
                    )
                ).scalars()
            )

        assert {str(value) for value in visible} == {GRANT_B}

        with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            _insert_grant(
                connection,
                grant_id=("00000000-0000-7600-8000-000000001041"),
                tenant_id=TENANT_B,
                actor_id=ACTOR_B,
                issuer_id=ISSUER_B,
            )

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            updated = connection.execute(
                text(
                    """
                    UPDATE platform.break_glass_grant
                    SET
                        status = 'SUSPENDED',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )

            assert updated.rowcount == 1

        with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            connection.execute(
                text(
                    """
                    UPDATE platform.break_glass_grant
                    SET
                        status = 'ACTIVE',
                        version = version + 2,
                        updated_at = clock_timestamp()
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            connection.execute(
                text(
                    """
                    UPDATE platform.break_glass_grant
                    SET
                        reason = 'Tampered reason',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )

        with runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            connection.execute(
                text(
                    """
                    UPDATE platform.break_glass_grant
                    SET
                        status = 'REVOKED',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )

        with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            connection.execute(
                text(
                    """
                    UPDATE platform.break_glass_grant
                    SET
                        status = 'ACTIVE',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )

        invalid_statements = (
            """
            INSERT INTO platform.break_glass_grant (
                id,
                tenant_id,
                actor_id,
                issued_by_actor_id,
                capabilities,
                scope_kind,
                resource_type,
                resource_id,
                reason,
                valid_from,
                valid_until,
                status,
                accepted_acr_values,
                required_amr
            )
            VALUES (
                '00000000-0000-7600-8000-000000001051',
                :tenant_id,
                :actor_id,
                :issuer_id,
                ARRAY['platform.outbox.retry'],
                'RESOURCE',
                'outbox-message',
                NULL,
                'Invalid scope',
                now(),
                now() + interval '10 minutes',
                'ACTIVE',
                ARRAY['elevated'],
                ARRAY[]::varchar[]
            )
            """,
            """
            INSERT INTO platform.break_glass_grant (
                id,
                tenant_id,
                actor_id,
                issued_by_actor_id,
                capabilities,
                scope_kind,
                reason,
                valid_from,
                valid_until,
                status,
                accepted_acr_values,
                required_amr
            )
            VALUES (
                '00000000-0000-7600-8000-000000001052',
                :tenant_id,
                :actor_id,
                :issuer_id,
                ARRAY['platform.outbox.retry'],
                'TENANT',
                'Invalid validity',
                now(),
                now(),
                'ACTIVE',
                ARRAY['elevated'],
                ARRAY[]::varchar[]
            )
            """,
            """
            INSERT INTO platform.break_glass_grant (
                id,
                tenant_id,
                actor_id,
                issued_by_actor_id,
                capabilities,
                scope_kind,
                reason,
                valid_from,
                valid_until,
                status,
                accepted_acr_values,
                required_amr
            )
            VALUES (
                '00000000-0000-7600-8000-000000001053',
                :tenant_id,
                :actor_id,
                :issuer_id,
                ARRAY['platform.outbox.retry'],
                'TENANT',
                'Invalid assurance',
                now(),
                now() + interval '10 minutes',
                'ACTIVE',
                ARRAY[]::varchar[],
                ARRAY[]::varchar[]
            )
            """,
        )

        for statement in invalid_statements:
            with pytest.raises(IntegrityError), runtime_engine.begin() as connection:
                _set_tenant(
                    connection,
                    TENANT_A,
                )

                connection.execute(
                    text(statement),
                    {
                        "tenant_id": TENANT_A,
                        "actor_id": ACTOR_A,
                        "issuer_id": ISSUER_A,
                    },
                )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(
                connection,
                TENANT_A,
            )

            connection.execute(
                text(
                    """
                    DELETE FROM platform.break_glass_grant
                    WHERE id =
                        CAST(:grant_id AS uuid)
                    """
                ),
                {"grant_id": GRANT_A},
            )
