from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from core_platform.foundation.canonical_json import canonical_json_bytes
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.ids import (
    ActorId,
    EvidenceRecordId,
    TenantId,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    envelope_version: int
    record_id: EvidenceRecordId
    tenant_id: TenantId
    audit_record_id: UUID
    transaction_id: UUID
    actor_id: ActorId
    correlation_id: CorrelationId
    evidence_type: str
    occurred_at: datetime
    signed_at: datetime
    payload_hash: str
    signature_algorithm: str
    key_id: str

    def __post_init__(self) -> None:
        if self.envelope_version < 1:
            raise ValueError("envelope_version must be >= 1")

        if not self.evidence_type.strip():
            raise ValueError("evidence_type must not be empty")

        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.signed_at, "signed_at")

        if self.signed_at < self.occurred_at:
            raise ValueError("signed_at must not precede occurred_at")

        if not self.payload_hash.startswith("sha256:"):
            raise ValueError("payload_hash must use sha256")

        if not self.signature_algorithm.strip():
            raise ValueError("signature_algorithm must not be empty")

        if not self.key_id.strip():
            raise ValueError("key_id must not be empty")

    def signing_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "actor_id": str(self.actor_id),
                "audit_record_id": str(self.audit_record_id),
                "correlation_id": str(self.correlation_id),
                "envelope_version": self.envelope_version,
                "evidence_type": self.evidence_type,
                "key_id": self.key_id,
                "occurred_at": _utc_timestamp(self.occurred_at),
                "payload_hash": self.payload_hash,
                "record_id": str(self.record_id),
                "signature_algorithm": self.signature_algorithm,
                "signed_at": _utc_timestamp(self.signed_at),
                "tenant_id": str(self.tenant_id),
                "transaction_id": str(self.transaction_id),
            }
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    envelope: EvidenceEnvelope
    canonical_payload: bytes
    signature: bytes

    def __post_init__(self) -> None:
        if not self.canonical_payload:
            raise ValueError("canonical_payload must not be empty")

        if not self.signature:
            raise ValueError("signature must not be empty")

    def payload_hash_matches(self) -> bool:
        digest = hashlib.sha256(self.canonical_payload).hexdigest()
        return self.envelope.payload_hash == f"sha256:{digest}"
