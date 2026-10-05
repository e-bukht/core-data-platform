from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_ID = TenantId(
    UUID("00000000-0000-7700-8000-000000001001")
)
ACTOR_ID = ActorId(
    UUID("00000000-0000-7700-8000-000000001002")
)
CORRELATION_ID = CorrelationId(
    UUID("00000000-0000-7700-8000-000000001003")
)

OCCURRED_AT = datetime(
    2026,
    9,
    26,
    18,
    45,
    tzinfo=UTC,
)


def _run(
    coro: Coroutine[Any, Any, None],
) -> None:
    def loop_factory() -> asyncio.AbstractEventLoop:
        return asyncio.SelectorEventLoop(
            selectors.SelectSelector()
        )

    with asyncio.Runner(
        loop_factory=loop_factory
    ) as runner:
        runner.run(coro)


def _seed(migration_url: str) -> None:
    engine = create_engine(migration_url)

    try:
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
                        'evidence-atomicity',
                        'Evidence Atomicity Tenant',
                        'ACTIVE'
                    )
                    """
                ),
                {"tenant_id": str(TENANT_ID.value)},
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
                        'Evidence Atomicity Actor'
                    )
                    """
                ),
                {"actor_id": str(ACTOR_ID.value)},
            )
    finally:
        engine.dispose()


def _context(
    suffix: int,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(
            UUID(
                f"00000000-0000-7701-8000-{suffix:012d}"
            )
        ),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="evidence.atomicity",
        capability="evidence.atomicity",
        started_at=OCCURRED_AT,
    )


def _audit(
    context: TransactionContext,
    suffix: int,
) -> AuditRecord:
    return AuditRecord(
        record_id=AuditRecordId(
            UUID(
                f"00000000-0000-7702-8000-{suffix:012d}"
            )
        ),
        tenant_id=context.tenant_id,
        transaction_id=context.transaction_id,
        actor_id=context.actor_id,
        correlation_id=context.correlation_id,
        capability=context.capability,
        action=context.operation,
        resource_type="EvidenceProbe",
        resource_id=f"probe-{suffix}",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=OCCURRED_AT,
        details={
            "suffix": suffix,
            "purpose": "evidence-atomicity",
        },
    )


def _evidence(
    context: TransactionContext,
    audit: AuditRecord,
    suffix: int,
) -> EvidenceRecord:
    payload = {
        "audit_record_id": str(
            audit.record_id.value
        ),
        "outcome": audit.outcome.value,
        "resource_id": audit.resource_id,
    }

    return EvidenceRecord(
        envelope=EvidenceEnvelope(
            envelope_version=1,
            record_id=EvidenceRecordId(
                UUID(
                    f"00000000-0000-7703-8000-{suffix:012d}"
                )
            ),
            tenant_id=context.tenant_id,
            audit_record_id=audit.record_id.value,
            transaction_id=context.transaction_id.value,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            evidence_type="transaction.audit",
            occurred_at=OCCURRED_AT,
            signed_at=OCCURRED_AT,
            payload_hash=canonical_json_sha256(payload),
            signature_algorithm="Ed25519",
            key_id="atomicity-test-key",
        ),
        canonical_payload=canonical_json_bytes(payload),
        signature=b"test-signature",
    )


async def _counts(
    database: Database,
    *,
    audit_id: AuditRecordId,
    evidence_id: EvidenceRecordId,
) -> tuple[int, int]:
    async with database.tenant_transaction(
        TENANT_ID.value
    ) as connection:
        audit_count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.audit_record
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": str(audit_id.value)},
        )

        evidence_count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.evidence_record
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": str(evidence_id.value)},
        )

    return (
        int(audit_count or 0),
        int(evidence_count or 0),
    )


async def _exercise(
    runtime_url: str,
) -> None:
    database = Database(
        runtime_url,
        pool_size=2,
        max_overflow=0,
    )
    factory = PostgresUnitOfWorkFactory(database)

    try:
        # ------------------------------------------------------
        # 1. Audit + Evidence commit in the same transaction.
        # ------------------------------------------------------
        committed_context = _context(1101)
        committed_audit = _audit(
            committed_context,
            1101,
        )
        committed_evidence = _evidence(
            committed_context,
            committed_audit,
            1101,
        )

        uow = factory.create(committed_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await active.audit.append(
                committed_audit
            )
            await active.evidence.append(
                committed_evidence
            )
            await active.commit()

        assert await _counts(
            database,
            audit_id=committed_audit.record_id,
            evidence_id=(
                committed_evidence.envelope.record_id
            ),
        ) == (1, 1)

        # ------------------------------------------------------
        # 2. No commit => both records roll back.
        # ------------------------------------------------------
        rollback_context = _context(1102)
        rollback_audit = _audit(
            rollback_context,
            1102,
        )
        rollback_evidence = _evidence(
            rollback_context,
            rollback_audit,
            1102,
        )

        uow = factory.create(rollback_context)
        assert isinstance(uow, PostgresUnitOfWork)

        async with uow as active:
            await active.audit.append(
                rollback_audit
            )
            await active.evidence.append(
                rollback_evidence
            )
            # No explicit commit.

        assert await _counts(
            database,
            audit_id=rollback_audit.record_id,
            evidence_id=(
                rollback_evidence.envelope.record_id
            ),
        ) == (0, 0)

        # ------------------------------------------------------
        # 3. Evidence FK failure rolls back prior Audit insert.
        # ------------------------------------------------------
        failure_context = _context(1103)
        failure_audit = _audit(
            failure_context,
            1103,
        )
        valid_evidence = _evidence(
            failure_context,
            failure_audit,
            1103,
        )

        broken_evidence = replace(
            valid_evidence,
            envelope=replace(
                valid_evidence.envelope,
                audit_record_id=UUID(
                    "00000000-0000-7702-8000-000000009999"
                ),
            ),
        )

        uow = factory.create(failure_context)
        assert isinstance(uow, PostgresUnitOfWork)

        with pytest.raises(IntegrityError):
            async with uow as active:
                await active.audit.append(
                    failure_audit
                )
                await active.evidence.append(
                    broken_evidence
                )
                await active.commit()

        assert await _counts(
            database,
            audit_id=failure_audit.record_id,
            evidence_id=(
                broken_evidence.envelope.record_id
            ),
        ) == (0, 0)

    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_audit_and_evidence_share_atomic_uow(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(
            admin_url(postgres)
        )

        run_alembic(
            migration_url,
            runtime_url,
        )

        _seed(migration_url)

        _run(
            _exercise(runtime_url)
        )