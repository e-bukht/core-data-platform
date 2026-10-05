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

TENANT_ID = "00000000-0000-7700-8000-000000001001"

ACTOR_ID = "00000000-0000-7700-8000-000000001002"
ISSUER_ID = "00000000-0000-7700-8000-000000001003"

AUDIT_ID = "00000000-0000-7700-8000-000000001004"
TRANSACTION_ID = "00000000-0000-7700-8000-000000001005"
CORRELATION_ID = "00000000-0000-7700-8000-000000001006"
EVIDENCE_ID = "00000000-0000-7700-8000-000000001007"

BREAK_GLASS_ID = "00000000-0000-7700-8000-000000001008"

VALID_HASH = "sha256:" + ("c" * 64)


def _set_tenant(
    connection: Connection,
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
def test_evidence_schema_upgrades_exactly_to_break_glass(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(
            admin_url(postgres)
        )

        # ------------------------------------------------------
        # 1. Establish exact 0004 Evidence boundary.
        # ------------------------------------------------------
        run_alembic(
            migration_url,
            runtime_url,
            "0004_evidence",
        )

        migration_engine = create_engine(
            migration_url
        )

        try:
            with migration_engine.begin() as connection:
                revision = connection.scalar(
                    text(
                        """
                        SELECT version_num
                        FROM alembic_version
                        """
                    )
                )

                break_glass_relation = connection.scalar(
                    text(
                        """
                        SELECT to_regclass(
                            'platform.break_glass_grant'
                        )
                        """
                    )
                )

                assert revision == "0004_evidence"
                assert break_glass_relation is None

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
                            'break-glass-upgrade',
                            'Break Glass Upgrade',
                            'ACTIVE'
                        )
                        """
                    ),
                    {"tenant_id": TENANT_ID},
                )

                for actor_id, display_name in (
                    (
                        ACTOR_ID,
                        "Break Glass Subject",
                    ),
                    (
                        ISSUER_ID,
                        "Break Glass Issuer",
                    ),
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
                                :display_name
                            )
                            """
                        ),
                        {
                            "actor_id": actor_id,
                            "display_name": display_name,
                        },
                    )

            with migration_engine.begin() as connection:
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
                            'upgrade.break-glass',
                            'upgrade.break-glass',
                            'UpgradeProbe',
                            'probe-001',
                            'SUCCESS',
                            now(),
                            '{"phase":"0004"}'::jsonb
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
                            'upgrade-break-glass-key',
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

        finally:
            migration_engine.dispose()

        # ------------------------------------------------------
        # 2. Execute exactly 0004 -> 0005.
        # ------------------------------------------------------
        run_alembic(
            migration_url,
            runtime_url,
            "0005_break_glass",
        )

        migration_engine = create_engine(
            migration_url
        )
        runtime_engine = create_engine(
            runtime_url
        )

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

                break_glass_relation = connection.scalar(
                    text(
                        """
                        SELECT to_regclass(
                            'platform.break_glass_grant'
                        )
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

                assert revision == "0005_break_glass"
                assert (
                    break_glass_relation
                    == "platform.break_glass_grant"
                )
                assert (
                    evidence_relation
                    == "platform.evidence_record"
                )

            # --------------------------------------------------
            # 3. Existing Evidence must be preserved exactly.
            # --------------------------------------------------
            with migration_engine.begin() as connection:
                _set_tenant(connection)

                evidence = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                id,
                                tenant_id,
                                audit_record_id,
                                transaction_id,
                                actor_id,
                                correlation_id,
                                envelope_version,
                                evidence_type,
                                payload_hash,
                                signature_algorithm,
                                key_id,
                                encode(
                                    canonical_payload,
                                    'hex'
                                ) AS payload_hex,
                                encode(
                                    signature,
                                    'hex'
                                ) AS signature_hex
                            FROM platform.evidence_record
                            WHERE id =
                                CAST(:evidence_id AS uuid)
                            """
                        ),
                        {
                            "evidence_id": EVIDENCE_ID,
                        },
                    )
                    .mappings()
                    .one()
                )

            assert str(evidence["id"]) == EVIDENCE_ID
            assert str(evidence["tenant_id"]) == TENANT_ID
            assert str(evidence["audit_record_id"]) == AUDIT_ID
            assert (
                str(evidence["transaction_id"])
                == TRANSACTION_ID
            )
            assert str(evidence["actor_id"]) == ACTOR_ID
            assert (
                str(evidence["correlation_id"])
                == CORRELATION_ID
            )
            assert evidence["envelope_version"] == 1
            assert evidence["evidence_type"] == (
                "transaction.audit"
            )
            assert evidence["payload_hash"] == VALID_HASH
            assert evidence["signature_algorithm"] == "Ed25519"
            assert evidence["key_id"] == (
                "upgrade-break-glass-key"
            )
            assert evidence["payload_hex"] == "7b7d"
            assert evidence["signature_hex"] == "00"

            # --------------------------------------------------
            # 4. Runtime can create a new tenant-scoped grant.
            # --------------------------------------------------
            with runtime_engine.begin() as connection:
                _set_tenant(connection)

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
                            'Upgrade recovery grant',
                            now(),
                            now() + interval '20 minutes',
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
                        "grant_id": BREAK_GLASS_ID,
                        "tenant_id": TENANT_ID,
                        "actor_id": ACTOR_ID,
                        "issuer_id": ISSUER_ID,
                    },
                )

            with runtime_engine.begin() as connection:
                _set_tenant(connection)

                grant = (
                    connection.execute(
                        text(
                            """
                            SELECT
                                id,
                                tenant_id,
                                actor_id,
                                issued_by_actor_id,
                                status,
                                version
                            FROM platform.break_glass_grant
                            WHERE id =
                                CAST(:grant_id AS uuid)
                            """
                        ),
                        {
                            "grant_id": BREAK_GLASS_ID,
                        },
                    )
                    .mappings()
                    .one()
                )

            assert str(grant["id"]) == BREAK_GLASS_ID
            assert str(grant["tenant_id"]) == TENANT_ID
            assert str(grant["actor_id"]) == ACTOR_ID
            assert (
                str(grant["issued_by_actor_id"])
                == ISSUER_ID
            )
            assert grant["status"] == "ACTIVE"
            assert grant["version"] == 0

        finally:
            runtime_engine.dispose()
            migration_engine.dispose()