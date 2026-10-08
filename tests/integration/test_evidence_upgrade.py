from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from testcontainers.community.postgres import PostgresContainer

from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = "00000000-0000-7500-8000-000000001001"
ACTOR_ID = "00000000-0000-7500-8000-000000001002"
AUDIT_ID = "00000000-0000-7500-8000-000000001003"
TRANSACTION_ID = "00000000-0000-7500-8000-000000001004"
CORRELATION_ID = "00000000-0000-7500-8000-000000001005"
EVIDENCE_ID = "00000000-0000-7500-8000-000000001006"

VALID_HASH = "sha256:" + ("b" * 64)


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


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_p0_i3_upgrades_exactly_to_evidence_schema(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))

        # ------------------------------------------------------
        # 1. Establish the certified P0-I3 schema boundary.
        # ------------------------------------------------------
        run_alembic(
            migration_url,
            runtime_url,
            "0003_transaction_kernel",
        )

        engine = create_engine(migration_url)

        try:
            with engine.begin() as connection:
                revision = connection.scalar(
                    text(
                        """
                        SELECT version_num
                        FROM alembic_version
                        """
                    )
                )

                evidence_relation = connection.scalar(
                    text(
                        """
                        SELECT to_regclass(
                            'platform.evidence_record'
                        )
                        """
                    )
                )

                assert revision == "0003_transaction_kernel"
                assert evidence_relation is None

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
                            'p0-i3-evidence-upgrade',
                            'P0-I3 Evidence Upgrade',
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
                            'SERVICE',
                            'ACTIVE',
                            'P0-I3 Evidence Actor'
                        )
                        """
                    ),
                    {"actor_id": ACTOR_ID},
                )

            with engine.begin() as connection:
                _set_tenant(connection)

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
                            'upgrade.evidence',
                            'upgrade.evidence',
                            'UpgradeProbe',
                            'probe-001',
                            'SUCCESS',
                            now(),
                            '{"phase":"p0-i3"}'::jsonb
                        )
                        """
                    ),
                    {
                        "audit_id": AUDIT_ID,
                        "tenant_id": TENANT_ID,
                        "transaction_id": TRANSACTION_ID,
                        "actor_id": ACTOR_ID,
                        "correlation_id": CORRELATION_ID,
                    },
                )
        finally:
            engine.dispose()

        # ------------------------------------------------------
        # 2. Execute exactly P0-I3 -> P0-I4 Evidence migration.
        # ------------------------------------------------------
        run_alembic(
            migration_url,
            runtime_url,
            "0004_evidence",
        )

        migration_engine = create_engine(migration_url)
        runtime_engine = create_engine(runtime_url)

        try:
            with migration_engine.connect() as connection:
                revision = connection.scalar(
                    text(
                        """
                        SELECT version_num
                        FROM alembic_version
                        """
                    )
                )

                evidence_relation = connection.scalar(
                    text(
                        """
                        SELECT to_regclass(
                            'platform.evidence_record'
                        )
                        """
                    )
                )

                audit_identity_constraint = connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_constraint
                        WHERE conrelid =
                            'platform.audit_record'::regclass
                          AND conname =
                            'uq_audit_record_evidence_identity'
                        """
                    )
                )

                evidence_fk = connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_constraint
                        WHERE conrelid =
                            'platform.evidence_record'::regclass
                          AND conname =
                            'fk_evidence_record_audit_context'
                        """
                    )
                )

                assert revision == "0004_evidence"
                assert evidence_relation == "platform.evidence_record"
                assert audit_identity_constraint == 1
                assert evidence_fk == 1

            # --------------------------------------------------
            # 3. Existing P0-I3 audit data must be preserved.
            # --------------------------------------------------
            with migration_engine.begin() as connection:
                _set_tenant(connection)

                audit = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                id,
                                tenant_id,
                                transaction_id,
                                actor_id,
                                correlation_id,
                                action,
                                details
                            FROM platform.audit_record
                            WHERE id =
                                CAST(:audit_id AS uuid)
                            """
                        ),
                        {"audit_id": AUDIT_ID},
                    )
                    .mappings()
                    .one()
                )

            assert str(audit["id"]) == AUDIT_ID
            assert str(audit["tenant_id"]) == TENANT_ID
            assert str(audit["transaction_id"]) == TRANSACTION_ID
            assert str(audit["actor_id"]) == ACTOR_ID
            assert str(audit["correlation_id"]) == CORRELATION_ID
            assert audit["action"] == "upgrade.evidence"
            assert audit["details"] == {"phase": "p0-i3"}

            # --------------------------------------------------
            # 4. New Evidence can reference the old audit.
            # --------------------------------------------------
            with runtime_engine.begin() as connection:
                _set_tenant(connection)

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
                            'upgrade-test-key',
                            decode('7b7d', 'hex'),
                            decode('00', 'hex')
                        )
                        """
                    ),
                    {
                        "evidence_id": EVIDENCE_ID,
                        "tenant_id": TENANT_ID,
                        "audit_id": AUDIT_ID,
                        "transaction_id": TRANSACTION_ID,
                        "actor_id": ACTOR_ID,
                        "correlation_id": CORRELATION_ID,
                        "payload_hash": VALID_HASH,
                    },
                )

            with runtime_engine.begin() as connection:
                _set_tenant(connection)

                evidence_count = connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM platform.evidence_record
                        WHERE id =
                            CAST(:evidence_id AS uuid)
                        """
                    ),
                    {"evidence_id": EVIDENCE_ID},
                )

            assert evidence_count == 1

        finally:
            runtime_engine.dispose()
            migration_engine.dispose()
