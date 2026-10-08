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

TENANT_A = "00000000-0000-7400-8000-000000001001"
TENANT_B = "00000000-0000-7400-8000-000000001002"

ACTOR_A = "00000000-0000-7400-8000-000000001011"
ACTOR_B = "00000000-0000-7400-8000-000000001012"

AUDIT_A = "00000000-0000-7400-8000-000000001021"
AUDIT_B = "00000000-0000-7400-8000-000000001022"

TRANSACTION_A = "00000000-0000-7400-8000-000000001031"
TRANSACTION_B = "00000000-0000-7400-8000-000000001032"

CORRELATION_A = "00000000-0000-7400-8000-000000001041"
CORRELATION_B = "00000000-0000-7400-8000-000000001042"

EVIDENCE_A = "00000000-0000-7400-8000-000000001051"
EVIDENCE_B = "00000000-0000-7400-8000-000000001052"

VALID_HASH = "sha256:" + ("a" * 64)


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


def _seed_context_and_audits(engine: Engine) -> None:
    with engine.begin() as connection:
        for tenant_id, code in (
            (TENANT_A, "evidence-a"),
            (TENANT_B, "evidence-b"),
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
            (ACTOR_A, "Evidence Actor A"),
            (ACTOR_B, "Evidence Actor B"),
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
                        'SERVICE',
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

    with engine.begin() as connection:
        for (
            tenant_id,
            actor_id,
            audit_id,
            transaction_id,
            correlation_id,
        ) in (
            (
                TENANT_A,
                ACTOR_A,
                AUDIT_A,
                TRANSACTION_A,
                CORRELATION_A,
            ),
            (
                TENANT_B,
                ACTOR_B,
                AUDIT_B,
                TRANSACTION_B,
                CORRELATION_B,
            ),
        ):
            _set_tenant(connection, tenant_id)

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
                        CAST(:audit_id AS uuid),
                        CAST(:tenant_id AS uuid),
                        CAST(:transaction_id AS uuid),
                        CAST(:actor_id AS uuid),
                        CAST(:correlation_id AS uuid),
                        'evidence.create',
                        'evidence.create',
                        'EvidenceProbe',
                        :audit_id,
                        'SUCCESS',
                        now(),
                        '{}'::jsonb
                    )
                    """
                ),
                {
                    "audit_id": audit_id,
                    "tenant_id": tenant_id,
                    "transaction_id": transaction_id,
                    "actor_id": actor_id,
                    "correlation_id": correlation_id,
                },
            )


def _insert_evidence(
    connection: Connection,
    *,
    evidence_id: str,
    tenant_id: str,
    audit_id: str,
    transaction_id: str,
    actor_id: str,
    correlation_id: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO platform.evidence_record (
                id,
                tenant_id,
                audit_record_id,
                transaction_id,
                actor_id,
                correlation_id,
                envelope_version,
                evidence_type,
                occurred_at,
                signed_at,
                payload_hash,
                signature_algorithm,
                key_id,
                canonical_payload,
                signature
            )
            VALUES (
                CAST(:evidence_id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:audit_id AS uuid),
                CAST(:transaction_id AS uuid),
                CAST(:actor_id AS uuid),
                CAST(:correlation_id AS uuid),
                1,
                'transaction.audit',
                now(),
                now(),
                :payload_hash,
                'Ed25519',
                'integration-test-key',
                decode('7b7d', 'hex'),
                decode('00', 'hex')
            )
            """
        ),
        {
            "evidence_id": evidence_id,
            "tenant_id": tenant_id,
            "audit_id": audit_id,
            "transaction_id": transaction_id,
            "actor_id": actor_id,
            "correlation_id": correlation_id,
            "payload_hash": VALID_HASH,
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
def test_evidence_schema_is_tenant_safe_and_append_only(
    image: str,
) -> None:
    with _engines(image) as (
        migration_engine,
        runtime_engine,
    ):
        _seed_context_and_audits(migration_engine)

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
                              'evidence_record'
                        """
                    )
                )
                .mappings()
                .one()
            )

            constraint_names = set(
                connection.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid =
                            'platform.evidence_record'::regclass
                        """
                    )
                ).scalars()
            )

            privileges = (
                connection.execute(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                :runtime_role,
                                'platform.evidence_record',
                                'SELECT, INSERT'
                            ) AS read_insert,
                            has_table_privilege(
                                :runtime_role,
                                'platform.evidence_record',
                                'UPDATE'
                            ) AS can_update,
                            has_table_privilege(
                                :runtime_role,
                                'platform.evidence_record',
                                'DELETE'
                            ) AS can_delete
                        """
                    ),
                    {"runtime_role": RUNTIME_ROLE},
                )
                .mappings()
                .one()
            )

        assert table_state["owner"] != RUNTIME_ROLE
        assert table_state["relrowsecurity"] is True
        assert table_state["relforcerowsecurity"] is True

        assert "fk_evidence_record_audit_context" in constraint_names
        assert privileges["read_insert"] is True
        assert privileges["can_update"] is False
        assert privileges["can_delete"] is False

        with runtime_engine.begin() as connection:
            _set_tenant(connection, TENANT_A)
            _insert_evidence(
                connection,
                evidence_id=EVIDENCE_A,
                tenant_id=TENANT_A,
                audit_id=AUDIT_A,
                transaction_id=TRANSACTION_A,
                actor_id=ACTOR_A,
                correlation_id=CORRELATION_A,
            )

        with runtime_engine.begin() as connection:
            _set_tenant(connection, TENANT_B)
            _insert_evidence(
                connection,
                evidence_id=EVIDENCE_B,
                tenant_id=TENANT_B,
                audit_id=AUDIT_B,
                transaction_id=TRANSACTION_B,
                actor_id=ACTOR_B,
                correlation_id=CORRELATION_B,
            )

        with runtime_engine.connect() as connection:
            count = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM platform.evidence_record
                    """
                )
            )

        assert count == 0

        with runtime_engine.begin() as connection:
            _set_tenant(connection, TENANT_A)

            visible_ids = set(
                connection.execute(
                    text(
                        """
                        SELECT id
                        FROM platform.evidence_record
                        """
                    )
                ).scalars()
            )

        assert {str(value) for value in visible_ids} == {EVIDENCE_A}

        with runtime_engine.begin() as connection:
            _set_tenant(connection, TENANT_B)

            visible_ids = set(
                connection.execute(
                    text(
                        """
                        SELECT id
                        FROM platform.evidence_record
                        """
                    )
                ).scalars()
            )

        assert {str(value) for value in visible_ids} == {EVIDENCE_B}

        with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
            _set_tenant(connection, TENANT_A)

            _insert_evidence(
                connection,
                evidence_id=("00000000-0000-7400-8000-000000001061"),
                tenant_id=TENANT_B,
                audit_id=AUDIT_B,
                transaction_id=TRANSACTION_B,
                actor_id=ACTOR_B,
                correlation_id=CORRELATION_B,
            )

        mismatches = (
            {
                "evidence_id": "00000000-0000-7400-8000-000000001062",
                "audit_id": AUDIT_B,
                "transaction_id": TRANSACTION_B,
                "actor_id": ACTOR_B,
                "correlation_id": CORRELATION_B,
            },
            {
                "evidence_id": "00000000-0000-7400-8000-000000001063",
                "audit_id": AUDIT_A,
                "transaction_id": TRANSACTION_B,
                "actor_id": ACTOR_A,
                "correlation_id": CORRELATION_A,
            },
            {
                "evidence_id": "00000000-0000-7400-8000-000000001064",
                "audit_id": AUDIT_A,
                "transaction_id": TRANSACTION_A,
                "actor_id": ACTOR_B,
                "correlation_id": CORRELATION_A,
            },
            {
                "evidence_id": "00000000-0000-7400-8000-000000001065",
                "audit_id": AUDIT_A,
                "transaction_id": TRANSACTION_A,
                "actor_id": ACTOR_A,
                "correlation_id": CORRELATION_B,
            },
        )

        for mismatch in mismatches:
            with pytest.raises(IntegrityError), runtime_engine.begin() as connection:
                _set_tenant(connection, TENANT_A)

                _insert_evidence(
                    connection,
                    tenant_id=TENANT_A,
                    **mismatch,
                )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(connection, TENANT_A)

            connection.execute(
                text(
                    """
                    UPDATE platform.evidence_record
                    SET evidence_type = 'tampered'
                    WHERE id =
                        CAST(:evidence_id AS uuid)
                    """
                ),
                {"evidence_id": EVIDENCE_A},
            )

        with pytest.raises(DBAPIError), migration_engine.begin() as connection:
            _set_tenant(connection, TENANT_A)

            connection.execute(
                text(
                    """
                    DELETE FROM platform.evidence_record
                    WHERE id =
                        CAST(:evidence_id AS uuid)
                    """
                ),
                {"evidence_id": EVIDENCE_A},
            )
