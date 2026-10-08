from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.evidence_store import (
    PostgresEvidenceRepository,
)
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import TransactionId
from core_platform.transaction_kernel.models import TransactionContext

TENANT_ID = TenantId(UUID("00000000-0000-7600-8000-000000001001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7600-8000-000000001002"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7600-8000-000000001003"))
TRANSACTION_ID = TransactionId(UUID("00000000-0000-7600-8000-000000001004"))
AUDIT_ID = UUID("00000000-0000-7600-8000-000000001005")

NOW = datetime(
    2026,
    9,
    26,
    18,
    30,
    tzinfo=UTC,
)


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="evidence.create",
        capability="evidence.create",
        started_at=NOW,
    )


def _record() -> EvidenceRecord:
    payload = {
        "action": "evidence.create",
        "outcome": "SUCCESS",
    }

    canonical_payload = canonical_json_bytes(payload)

    return EvidenceRecord(
        envelope=EvidenceEnvelope(
            envelope_version=1,
            record_id=EvidenceRecordId(UUID("00000000-0000-7600-8000-000000001006")),
            tenant_id=TENANT_ID,
            audit_record_id=AUDIT_ID,
            transaction_id=TRANSACTION_ID.value,
            actor_id=ACTOR_ID,
            correlation_id=CORRELATION_ID,
            evidence_type="transaction.audit",
            occurred_at=NOW,
            signed_at=NOW,
            payload_hash=canonical_json_sha256(payload),
            signature_algorithm="Ed25519",
            key_id="test-key",
        ),
        canonical_payload=canonical_payload,
        signature=b"signature",
    )


class _UnusedConnection:
    def __call__(self) -> None:
        raise AssertionError("Database must not be touched after trust guard failure")


def _assert_context_divergence(
    envelope: EvidenceEnvelope,
    message: str,
) -> None:
    async def run() -> None:
        record = _record()

        repository = PostgresEvidenceRepository(
            _UnusedConnection(),  # type: ignore[arg-type]
            _context(),
        )

        with pytest.raises(
            ValueError,
            match=message,
        ):
            await repository.append(
                replace(
                    record,
                    envelope=envelope,
                )
            )

    asyncio.run(run())


def test_append_rejects_tenant_divergence_before_io() -> None:
    record = _record()

    _assert_context_divergence(
        replace(
            record.envelope,
            tenant_id=TenantId(UUID("00000000-0000-7600-8000-000000009001")),
        ),
        "Evidence tenant does not match UnitOfWork",
    )


def test_append_rejects_transaction_divergence_before_io() -> None:
    record = _record()

    _assert_context_divergence(
        replace(
            record.envelope,
            transaction_id=UUID("00000000-0000-7600-8000-000000009002"),
        ),
        "Evidence transaction does not match UnitOfWork",
    )


def test_append_rejects_actor_divergence_before_io() -> None:
    record = _record()

    _assert_context_divergence(
        replace(
            record.envelope,
            actor_id=ActorId(UUID("00000000-0000-7600-8000-000000009003")),
        ),
        "Evidence actor does not match UnitOfWork",
    )


def test_append_rejects_correlation_divergence_before_io() -> None:
    record = _record()

    _assert_context_divergence(
        replace(
            record.envelope,
            correlation_id=CorrelationId(UUID("00000000-0000-7600-8000-000000009004")),
        ),
        "Evidence correlation does not match UnitOfWork",
    )


def test_append_rejects_payload_hash_divergence_before_io() -> None:
    async def run() -> None:
        record = replace(
            _record(),
            canonical_payload=b'{"tampered":true}',
        )

        repository = PostgresEvidenceRepository(
            _UnusedConnection(),  # type: ignore[arg-type]
            _context(),
        )

        with pytest.raises(
            ValueError,
            match=("Evidence payload hash does not match canonical payload"),
        ):
            await repository.append(record)

    asyncio.run(run())
