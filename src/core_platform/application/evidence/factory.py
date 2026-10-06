from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from core_platform.foundation.canonical_json import (
    JsonValue,
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.temporal import Clock
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
    EvidenceSigner,
)


class SignedEvidenceFactory:
    """Build and sign evidence without persisting it."""

    def __init__(
        self,
        *,
        signer: EvidenceSigner,
        clock: Clock,
    ) -> None:
        self._signer = signer
        self._clock = clock

    async def create(
        self,
        *,
        context: ExecutionContext,
        audit_record_id: UUID,
        transaction_id: UUID,
        evidence_type: str,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue],
        signed_at: datetime | None = None,
    ) -> EvidenceRecord:
        canonical_payload = canonical_json_bytes(
            payload
        )

        envelope = EvidenceEnvelope(
            envelope_version=1,
            record_id=EvidenceRecordId.new(),
            tenant_id=context.tenant_id,
            audit_record_id=audit_record_id,
            transaction_id=transaction_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            evidence_type=evidence_type,
            occurred_at=occurred_at,
            signed_at=(
                self._clock.now()
                if signed_at is None
                else signed_at
            ),
            payload_hash=canonical_json_sha256(
                payload
            ),
            signature_algorithm=(
                self._signer.algorithm
            ),
            key_id=self._signer.key_id,
        )

        signature = await self._signer.sign(
            envelope.signing_bytes()
        )

        return EvidenceRecord(
            envelope=envelope,
            canonical_payload=canonical_payload,
            signature=signature,
        )
