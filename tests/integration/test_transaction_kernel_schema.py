from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = "00000000-0000-7000-8000-000000000301"
ACTOR_ID = "00000000-0000-7000-8000-000000000302"
CORRELATION_ID = "00000000-0000-7000-8000-000000000303"
TRANSACTION_ID = "00000000-0000-7000-8000-000000000304"

IDEMPOTENCY_ID = "00000000-0000-7000-8000-000000000311"
OUTBOX_ID = "00000000-0000-7000-8000-000000000312"
INBOX_ID = "00000000-0000-7000-8000-000000000313"
AUDIT_ID = "00000000-0000-7000-8000-000000000314"

TENANT_SCOPED_TABLES = (
    "idempotency_record",
    "outbox_message",
    "inbox_message",
    "audit_record",
)


def _set_tenant(connection: Connection) -> None:
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
        {"tenant_id": TENANT_ID},
    )


def _seed_global_context(engine: Engine) -> None:
    with engine.begin() as connection:
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
                    'p0-i3-test',
                    'P0-I3 Test Tenant',
                    'ACTIVE'
                )
                """
            ),
            {"tenant_id": TENANT_ID},
        )

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
                    'SYSTEM',
                    'ACTIVE',
                    'P0-I3 Test Actor'
                )
                """
            ),
            {"actor_id": ACTOR_ID},
        )


def _seed_transaction_records(engine: Engine) -> None:
    with engine.begin() as connection:
        _set_tenant(connection)

        connection.execute(
            text(
                """
                INSERT INTO platform.idempotency_record (
                    id,
                    tenant_id,
                    operation,
                    idempotency_key,
                    request_hash,
                    status,
                    transaction_id,
                    created_at,
                    expires_at
                )
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    'test.operation',
                    'idem-001',
                    'sha256:test',
                    'IN_PROGRESS',
                    CAST(:transaction_id AS uuid),
                    now(),
                    now() + interval '1 day'
                )
                """
            ),
            {
                "id": IDEMPOTENCY_ID,
                "tenant_id": TENANT_ID,
                "transaction_id": TRANSACTION_ID,
            },
        )

        connection.execute(
            text(
                """
                INSERT INTO platform.outbox_message (
                    id,
                    tenant_id,
                    transaction_id,
                    actor_id,
                    message_type,
                    schema_version,
                    source,
                    occurred_at,
                    available_at,
                    correlation_id,
                    payload,
                    payload_hash
                )
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    CAST(:transaction_id AS uuid),
                    CAST(:actor_id AS uuid),
                    'test.event',
                    1,
                    'core-data-platform',
                    now(),
                    now(),
                    CAST(:correlation_id AS uuid),
                    '{}'::jsonb,
                    'sha256:test'
                )
                """
            ),
            {
                "id": OUTBOX_ID,
                "tenant_id": TENANT_ID,
                "transaction_id": TRANSACTION_ID,
                "actor_id": ACTOR_ID,
                "correlation_id": CORRELATION_ID,
            },
        )

        connection.execute(
            text(
                """
                INSERT INTO platform.inbox_message (
                    id,
                    tenant_id,
                    consumer_name,
                    message_id,
                    message_type,
                    correlation_id,
                    payload_hash,
                    received_at
                )
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    'test-consumer',
                    CAST(:message_id AS uuid),
                    'test.event',
                    CAST(:correlation_id AS uuid),
                    'sha256:test',
                    now()
                )
                """
            ),
            {
                "id": INBOX_ID,
                "tenant_id": TENANT_ID,
                "message_id": OUTBOX_ID,
                "correlation_id": CORRELATION_ID,
            },
        )

        connection.execute(
            text(
                """
                INSERT INTO platform.audit_record (
                    id,
                    tenant_id,
                    transaction_id,
                    actor_id,
                    correlation_id,
                    capability,
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    occurred_at,
                    details
                )
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    CAST(:transaction_id AS uuid),
                    CAST(:actor_id AS uuid),
                    CAST(:correlation_id AS uuid),
                    'test.capability',
                    'test.action',
                    'test-resource',
                    'resource-001',
                    'SUCCESS',
                    now(),
                    '{}'::jsonb
                )
                """
            ),
            {
                "id": AUDIT_ID,
                "tenant_id": TENANT_ID,
                "transaction_id": TRANSACTION_ID,
                "actor_id": ACTOR_ID,
                "correlation_id": CORRELATION_ID,
            },
        )


@contextmanager
def _engines(
    image: str,
) -> Iterator[tuple[Engine, Engine]]:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))
        run_alembic(migration_url, runtime_url)

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
    ["postgres:12.22", "postgres:18"],
)
def test_transaction_kernel_schema_security(
    image: str,
) -> None:
    with _engines(image) as (
        migration_engine,
        runtime_engine,
    ):
        _seed_global_context(migration_engine)
        _seed_transaction_records(migration_engine)

        with migration_engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        c.relname,
                        c.relrowsecurity,
                        c.relforcerowsecurity
                    FROM pg_class AS c
                    JOIN pg_namespace AS n
                        ON n.oid = c.relnamespace
                    WHERE n.nspname = 'platform'
                      AND c.relname = ANY(:tables)
                    ORDER BY c.relname
                    """
                ),
                {"tables": list(TENANT_SCOPED_TABLES)},
            ).mappings()

            rls = {
                row["relname"]: (
                    row["relrowsecurity"],
                    row["relforcerowsecurity"],
                )
                for row in rows
            }

        assert set(rls) == set(TENANT_SCOPED_TABLES)

        for table in TENANT_SCOPED_TABLES:
            assert rls[table] == (True, True)

        with migration_engine.connect() as connection:
            privileges = (
                connection.execute(
                    text(
                        """
                    SELECT
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.idempotency_record',
                            'SELECT, INSERT, UPDATE'
                        ) AS idempotency_dml,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.outbox_message',
                            'SELECT, INSERT, UPDATE'
                        ) AS outbox_dml,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.inbox_message',
                            'SELECT, INSERT, UPDATE'
                        ) AS inbox_dml,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.audit_record',
                            'SELECT, INSERT'
                        ) AS audit_insert,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.audit_record',
                            'UPDATE'
                        ) AS audit_update,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.audit_record',
                            'DELETE'
                        ) AS audit_delete,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.idempotency_record',
                            'DELETE'
                        ) AS idempotency_delete,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.outbox_message',
                            'DELETE'
                        ) AS outbox_delete,
                        has_table_privilege(
                            'coredata_runtime',
                            'platform.inbox_message',
                            'DELETE'
                        ) AS inbox_delete
                    """
                    )
                )
                .mappings()
                .one()
            )

        assert privileges["idempotency_dml"] is True
        assert privileges["outbox_dml"] is True
        assert privileges["inbox_dml"] is True
        assert privileges["audit_insert"] is True

        assert privileges["audit_update"] is False
        assert privileges["audit_delete"] is False
        assert privileges["idempotency_delete"] is False
        assert privileges["outbox_delete"] is False
        assert privileges["inbox_delete"] is False

        with runtime_engine.connect() as connection:
            for table in TENANT_SCOPED_TABLES:
                count = connection.execute(
                    text(f"SELECT count(*) FROM platform.{table}")
                ).scalar_one()

                assert count == 0

        with runtime_engine.begin() as connection:
            _set_tenant(connection)

            for table in TENANT_SCOPED_TABLES:
                count = connection.execute(
                    text(f"SELECT count(*) FROM platform.{table}")
                ).scalar_one()

                assert count == 1

        with pytest.raises(IntegrityError), runtime_engine.begin() as connection:
            _set_tenant(connection)
            connection.execute(
                text(
                    """
                        INSERT INTO platform.idempotency_record (
                            id,
                            tenant_id,
                            operation,
                            idempotency_key,
                            request_hash,
                            status,
                            transaction_id,
                            created_at,
                            expires_at
                        )
                        VALUES (
                            CAST(:id AS uuid),
                            CAST(:tenant_id AS uuid),
                            'test.operation',
                            'idem-001',
                            'sha256:test',
                            'IN_PROGRESS',
                            CAST(:transaction_id AS uuid),
                            now(),
                            now() + interval '1 day'
                        )
                        """
                ),
                {
                    "id": ("00000000-0000-7000-8000-000000000321"),
                    "tenant_id": TENANT_ID,
                    "transaction_id": TRANSACTION_ID,
                },
            )

        with pytest.raises(IntegrityError), runtime_engine.begin() as connection:
            _set_tenant(connection)
            connection.execute(
                text(
                    """
                        INSERT INTO platform.inbox_message (
                            id,
                            tenant_id,
                            consumer_name,
                            message_id,
                            message_type,
                            correlation_id,
                            payload_hash,
                            received_at
                        )
                        VALUES (
                            CAST(:id AS uuid),
                            CAST(:tenant_id AS uuid),
                            'test-consumer',
                            CAST(:message_id AS uuid),
                            'test.event',
                            CAST(:correlation_id AS uuid),
                            'sha256:test',
                            now()
                        )
                        """
                ),
                {
                    "id": ("00000000-0000-7000-8000-000000000322"),
                    "tenant_id": TENANT_ID,
                    "message_id": OUTBOX_ID,
                    "correlation_id": CORRELATION_ID,
                },
            )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(connection)
            connection.execute(
                text(
                    """
                        UPDATE platform.audit_record
                        SET action = 'mutated'
                        WHERE id = CAST(:id AS uuid)
                        """
                ),
                {"id": AUDIT_ID},
            )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(connection)
            connection.execute(
                text(
                    """
                        DELETE FROM platform.audit_record
                        WHERE id = CAST(:id AS uuid)
                        """
                ),
                {"id": AUDIT_ID},
            )
