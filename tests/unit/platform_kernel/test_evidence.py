from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import ActorId, TenantId


def _envelope(
    *,
    payload_hash: str,
    key_id: str = "evidence-key-2026-01",
) -> EvidenceEnvelope:
    occurred_at = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

    return EvidenceEnvelope(
        envelope_version=1,
        record_id=EvidenceRecordId(
            UUID("10000000-0000-7000-8000-000000000001")
        ),
        tenant_id=TenantId(
            UUID("20000000-0000-7000-8000-000000000001")
        ),
        audit_record_id=UUID(
            "30000000-0000-7000-8000-000000000001"
        ),
        transaction_id=UUID(
            "40000000-0000-7000-8000-000000000001"
        ),
        actor_id=ActorId(
            UUID("50000000-0000-7000-8000-000000000001")
        ),
        correlation_id=CorrelationId(
            UUID("60000000-0000-7000-8000-000000000001")
        ),
        evidence_type="transaction.audit",
        occurred_at=occurred_at,
        signed_at=occurred_at,
        payload_hash=payload_hash,
        signature_algorithm="Ed25519",
        key_id=key_id,
    )


def test_evidence_signing_envelope_is_deterministic() -> None:
    payload = {"action": "test-resource.create", "outcome": "SUCCESS"}
    envelope = _envelope(
        payload_hash=canonical_json_sha256(payload)
    )

    assert envelope.signing_bytes() == envelope.signing_bytes()
    assert b'"signature_algorithm":"Ed25519"' in envelope.signing_bytes()
    assert b'"key_id":"evidence-key-2026-01"' in envelope.signing_bytes()


def test_signing_key_metadata_is_covered_by_signed_envelope() -> None:
    payload_hash = canonical_json_sha256({"outcome": "SUCCESS"})
    first = _envelope(payload_hash=payload_hash)
    second = replace(first, key_id="evidence-key-2026-02")

    assert first.signing_bytes() != second.signing_bytes()


def test_evidence_detects_payload_tampering() -> None:
    original = {"amount": 100}
    tampered = {"amount": 101}

    envelope = _envelope(
        payload_hash=canonical_json_sha256(original)
    )

    original_record = EvidenceRecord(
        envelope=envelope,
        canonical_payload=canonical_json_bytes(original),
        signature=b"signed-evidence",
    )
    tampered_record = EvidenceRecord(
        envelope=envelope,
        canonical_payload=canonical_json_bytes(tampered),
        signature=b"signed-evidence",
    )

    assert original_record.payload_hash_matches()
    assert not tampered_record.payload_hash_matches()


def test_evidence_rejects_naive_timestamps() -> None:
    envelope = _envelope(
        payload_hash=canonical_json_sha256({"result": "ok"})
    )

    with pytest.raises(
        ValueError,
        match="occurred_at must be timezone-aware",
    ):
        replace(
            envelope,
            occurred_at=datetime(2026, 9, 25, 12, 0),
        )