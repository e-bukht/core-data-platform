from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from core_platform.application.evidence.factory import (
    SignedEvidenceFactory,
)
from core_platform.foundation.canonical_json import JsonValue
from core_platform.foundation.errors import ResourceNotFound
from core_platform.foundation.temporal import Clock
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import (
    EvidenceRecord,
    EvidenceRecordId,
    EvidenceRepository,
    EvidenceSigner,
    EvidenceVerifier,
)


class EvidenceVerificationStatus(StrEnum):
    VALID = "VALID"
    PAYLOAD_HASH_MISMATCH = "PAYLOAD_HASH_MISMATCH"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"


@dataclass(frozen=True, slots=True)
class EvidenceVerificationResult:
    record_id: EvidenceRecordId
    status: EvidenceVerificationStatus
    signature_algorithm: str
    key_id: str


class EvidenceService:
    def __init__(
        self,
        *,
        repository: EvidenceRepository,
        signer: EvidenceSigner,
        verifier: EvidenceVerifier,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._verifier = verifier
        self._factory = SignedEvidenceFactory(
            signer=signer,
            clock=clock,
        )

    async def create_evidence(
        self,
        *,
        context: ExecutionContext,
        audit_record_id: UUID,
        transaction_id: UUID,
        evidence_type: str,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue],
    ) -> EvidenceRecord:
        record = await self._factory.create(
            context=context,
            audit_record_id=audit_record_id,
            transaction_id=transaction_id,
            evidence_type=evidence_type,
            occurred_at=occurred_at,
            payload=payload,
        )

        await self._repository.append(record)

        return record

    async def verify_evidence(
        self,
        *,
        context: ExecutionContext,
        record_id: EvidenceRecordId,
    ) -> EvidenceVerificationResult:
        record = await self._repository.get(
            context.tenant_id,
            record_id,
        )

        if record is None or record.envelope.tenant_id != context.tenant_id:
            raise ResourceNotFound(
                "EVIDENCE.NOT_FOUND",
                "Evidence record was not found",
                correlation_id=str(context.correlation_id),
            )

        if not record.payload_hash_matches():
            return self._result(
                record,
                EvidenceVerificationStatus.PAYLOAD_HASH_MISMATCH,
            )

        signature_valid = await self._verifier.verify(
            record.envelope.signing_bytes(),
            signature=record.signature,
            algorithm=record.envelope.signature_algorithm,
            key_id=record.envelope.key_id,
        )

        return self._result(
            record,
            (
                EvidenceVerificationStatus.VALID
                if signature_valid
                else EvidenceVerificationStatus.SIGNATURE_INVALID
            ),
        )

    @staticmethod
    def _result(
        record: EvidenceRecord,
        status: EvidenceVerificationStatus,
    ) -> EvidenceVerificationResult:
        return EvidenceVerificationResult(
            record_id=record.envelope.record_id,
            status=status,
            signature_algorithm=record.envelope.signature_algorithm,
            key_id=record.envelope.key_id,
        )
