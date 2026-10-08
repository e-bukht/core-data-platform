from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.evidence_schema import (
    evidence_record,
)
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.models import TransactionContext

ConnectionProvider = Callable[[], AsyncConnection]


class PostgresEvidenceRepository:
    def __init__(
        self,
        connection: ConnectionProvider,
        context: TransactionContext,
    ) -> None:
        self._connection = connection
        self._context = context

    async def append(
        self,
        record: EvidenceRecord,
    ) -> None:
        envelope = record.envelope

        if envelope.tenant_id != self._context.tenant_id:
            raise ValueError("Evidence tenant does not match UnitOfWork")

        if envelope.transaction_id != self._context.transaction_id.value:
            raise ValueError("Evidence transaction does not match UnitOfWork")

        if envelope.actor_id != self._context.actor_id:
            raise ValueError("Evidence actor does not match UnitOfWork")

        if envelope.correlation_id != self._context.correlation_id:
            raise ValueError("Evidence correlation does not match UnitOfWork")

        if not record.payload_hash_matches():
            raise ValueError("Evidence payload hash does not match canonical payload")

        await self._connection().execute(
            evidence_record.insert().values(
                id=envelope.record_id.value,
                tenant_id=envelope.tenant_id.value,
                audit_record_id=envelope.audit_record_id,
                transaction_id=envelope.transaction_id,
                actor_id=envelope.actor_id.value,
                correlation_id=envelope.correlation_id.value,
                envelope_version=envelope.envelope_version,
                evidence_type=envelope.evidence_type,
                occurred_at=envelope.occurred_at,
                signed_at=envelope.signed_at,
                payload_hash=envelope.payload_hash,
                signature_algorithm=envelope.signature_algorithm,
                key_id=envelope.key_id,
                canonical_payload=record.canonical_payload,
                signature=record.signature,
            )
        )

    async def get(
        self,
        tenant_id: TenantId,
        record_id: EvidenceRecordId,
    ) -> EvidenceRecord | None:
        statement = select(evidence_record).where(
            evidence_record.c.tenant_id == tenant_id.value,
            evidence_record.c.id == record_id.value,
        )

        row = (await self._connection().execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return _evidence_from_row(row)


def _evidence_from_row(
    row: RowMapping,
) -> EvidenceRecord:
    envelope = EvidenceEnvelope(
        envelope_version=row["envelope_version"],
        record_id=EvidenceRecordId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        audit_record_id=row["audit_record_id"],
        transaction_id=row["transaction_id"],
        actor_id=ActorId(row["actor_id"]),
        correlation_id=CorrelationId(row["correlation_id"]),
        evidence_type=row["evidence_type"],
        occurred_at=row["occurred_at"],
        signed_at=row["signed_at"],
        payload_hash=row["payload_hash"],
        signature_algorithm=row["signature_algorithm"],
        key_id=row["key_id"],
    )

    return EvidenceRecord(
        envelope=envelope,
        canonical_payload=bytes(row["canonical_payload"]),
        signature=bytes(row["signature"]),
    )
