from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text

from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.evidence.models import (
    EvidenceEnvelope,
    EvidenceRecord,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    EvidenceRecordId,
    TenantId,
)
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)
from tests.test_platform.assertions import (
    assert_audit_persisted,
    assert_evidence_persisted,
)
from tests.test_platform.postgres import CertificationPostgres

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-00000000c301"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-00000000c302"))
TRANSACTION_ID = TransactionId(UUID("00000000-0000-7000-8000-00000000c303"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-00000000c304"))
AUDIT_ID = AuditRecordId(UUID("00000000-0000-7000-8000-00000000c305"))
EVIDENCE_ID = EvidenceRecordId(UUID("00000000-0000-7000-8000-00000000c306"))

NOW = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="certification.assertions",
        capability="platform.certification.read",
        started_at=NOW,
    )


def _audit(
    context: TransactionContext,
) -> AuditRecord:
    return AuditRecord(
        record_id=AUDIT_ID,
        tenant_id=context.tenant_id,
        transaction_id=context.transaction_id,
        actor_id=context.actor_id,
        correlation_id=context.correlation_id,
        capability=context.capability,
        action=context.operation,
        resource_type="CertificationProbe",
        resource_id="certification-resource",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=NOW,
        details={
            "purpose": "test-platform",
        },
    )


def _evidence(
    context: TransactionContext,
    audit: AuditRecord,
) -> EvidenceRecord:
    payload = {
        "audit_record_id": str(audit.record_id.value),
        "outcome": audit.outcome.value,
        "resource_id": audit.resource_id,
    }

    return EvidenceRecord(
        envelope=EvidenceEnvelope(
            envelope_version=1,
            record_id=EVIDENCE_ID,
            tenant_id=context.tenant_id,
            audit_record_id=audit.record_id.value,
            transaction_id=context.transaction_id.value,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            evidence_type="transaction.audit",
            occurred_at=NOW,
            signed_at=NOW,
            payload_hash=canonical_json_sha256(payload),
            signature_algorithm="Ed25519",
            key_id="certification-test-key",
        ),
        canonical_payload=canonical_json_bytes(payload),
        signature=b"certification-signature",
    )


def _seed_principals(
    postgres: CertificationPostgres,
) -> None:
    engine = create_engine(postgres.migration_url)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO platform.tenant(
                        id,
                        code,
                        display_name,
                        status
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        'certification-assertions',
                        'Certification Assertions',
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_id": str(TENANT_ID.value),
                },
            )

            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor(
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'SERVICE',
                        'ACTIVE',
                        'Certification Assertions Actor'
                    )
                    """
                ),
                {
                    "actor_id": str(ACTOR_ID.value),
                },
            )
    finally:
        engine.dispose()


async def _persist_and_assert(
    postgres: CertificationPostgres,
) -> None:
    context = _context()
    audit = _audit(context)
    evidence = _evidence(
        context,
        audit,
    )

    factory = PostgresUnitOfWorkFactory(postgres.database)

    uow = factory.create(context)

    assert isinstance(
        uow,
        PostgresUnitOfWork,
    )

    async with uow as active:
        await active.audit.append(audit)
        await active.evidence.append(evidence)
        await active.commit()

    await assert_audit_persisted(
        postgres.database,
        audit,
    )

    await assert_evidence_persisted(
        postgres.database,
        evidence,
    )


@pytest.mark.integration
def test_reusable_audit_and_evidence_assertions(
    cert_postgres: CertificationPostgres,
) -> None:
    _seed_principals(cert_postgres)

    asyncio.run(_persist_and_assert(cert_postgres))
